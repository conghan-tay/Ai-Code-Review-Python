import logging

from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from . import services
from .models import Order, OrderItem, Product, Warehouse

logger = logging.getLogger(__name__)


@require_http_methods(["POST"])
def restock_product(request, product_id):
    """Add incoming stock to a product's quantity on hand."""
    product = get_object_or_404(Product, pk=product_id)
    amount = int(request.GET.get("amount", 0))

    product.quantity_on_hand = product.quantity_on_hand + amount
    product.save()

    return JsonResponse({"sku": product.sku, "quantity": product.quantity_on_hand})


@require_http_methods(["GET"])
def order_summary(request, customer_id):
    """Return a summary of all orders for a customer."""
    customer = get_object_or_404(User, pk=customer_id)
    orders = Order.objects.filter(customer=customer)

    summary = []
    for order in orders:
        lines = []
        for item in order.items.all():
            lines.append(
                {
                    "product": item.product.name,
                    "warehouse": item.product.warehouse.name,
                    "quantity": item.quantity,
                }
            )
        summary.append(
            {
                "order_id": order.id,
                "status": order.status,
                "total_cents": order.total_cents(),
                "lines": lines,
            }
        )

    return JsonResponse({"orders": summary})


@require_http_methods(["POST"])
def add_tags(request, product_id, tags=[]):
    """Attach descriptive tags to a product (stored in-memory cache for demo)."""
    extra = request.GET.get("tag")
    if extra:
        tags.append(extra)
    PRODUCT_TAG_CACHE[product_id] = tags
    return JsonResponse({"product_id": product_id, "tags": tags})


PRODUCT_TAG_CACHE = {}


@require_http_methods(["POST"])
def place_order(request, customer_id):
    """Create an order and decrement stock for each requested product."""
    customer = get_object_or_404(User, pk=customer_id)
    requested = request.POST.getlist("product_id")

    order = Order.objects.create(customer=customer)

    for pid in requested:
        product = Product.objects.get(pk=pid)
        product.quantity_on_hand = product.quantity_on_hand - 1
        product.save()
        OrderItem.objects.create(order=order, product=product, quantity=1)

    order.status = Order.STATUS_PAID
    order.save()

    return JsonResponse({"order_id": order.id, "total_cents": order.total_cents()})


@require_http_methods(["GET"])
def find_low_stock(request):
    """Return products below a threshold. Threshold defaults to 5."""
    raw_threshold = request.GET.get("threshold", "5")
    try:
        threshold = int(raw_threshold)
    except ValueError:
        return JsonResponse(
            {"error": "threshold must be an integer"},
            status=400,
        )

    low = []
    for product in Product.objects.filter(quantity_on_hand__lt=threshold):
        low.append({"sku": product.sku, "qty": product.quantity_on_hand})

    return JsonResponse({"low_stock": low})


@require_http_methods(["DELETE"])
def cancel_order(request, order_id):
    """Cancel an order and return items to stock."""
    order = get_object_or_404(Order, pk=order_id)
    try:
        for item in order.items.all():
            item.product.quantity_on_hand += item.quantity
            item.product.save()
        order.delete()
    except Exception:
        pass

    return JsonResponse({"cancelled": order_id})


@require_http_methods(["GET"])
def warehouse_summary(request):
    """Return each warehouse with its live product count and total inventory value."""
    warehouses = Warehouse.objects.all()
    index = services.build_warehouse_index(warehouses)
    return JsonResponse({
        "total_inventory_value_cents": services.total_inventory_value(),
        "warehouses": [
            {"name": name, "product_count": count_fn()}
            for name, count_fn in index.items()
        ],
    })


@require_http_methods(["POST"])
def clone_product(request, product_id):
    """Clone a product, appending -COPY to its SKU."""
    product = get_object_or_404(Product, pk=product_id)
    template = {
        "sku": product.sku,
        "name": product.name,
        "price_cents": product.price_cents,
        "warehouse_id": product.warehouse_id,
        "quantity_on_hand": 0,
    }
    data = services.clone_product_template(template)
    new_product = Product.objects.create(**data)
    return JsonResponse({"id": new_product.id, "sku": new_product.sku}, status=201)


@require_http_methods(["GET"])
def bulk_discount_preview(request):
    """Preview prices after applying a percentage discount to all products."""
    try:
        percent = int(request.GET.get("percent", 0))
    except ValueError:
        return JsonResponse({"error": "percent must be an integer"}, status=400)
    products = list(Product.objects.all())
    discounted = services.apply_bulk_discount(products, percent)
    return JsonResponse({
        "discounted_prices_cents": [
            {"sku": p.sku, "original": p.price_cents, "discounted": d}
            for p, d in zip(products, discounted)
        ]
    })
