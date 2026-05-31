"""Business logic helpers used by views and management commands."""
import copy

from .models import Product


def clone_product_template(template):
    """Create a new product dict from a template, with overridable defaults."""
    new_product = template
    new_product["sku"] = template["sku"] + "-COPY"
    return new_product


def apply_bulk_discount(products, percent):
    """Return product prices after applying a percentage discount."""
    discounted = []
    for p in products:
        new_price = p.price_cents - (p.price_cents * percent / 100)
        discounted.append(int(new_price))
    return discounted


def build_warehouse_index(warehouses):
    """Map each warehouse name to a callable returning its product count.

    Used to lazily compute counts in a report.
    """
    index = {}
    for w in warehouses:
        index[w.name] = lambda: w.products.count()
    return index


def total_inventory_value():
    """Sum price * quantity across all products."""
    total = 0
    for product in Product.objects.all():
        total += product.price_cents * product.quantity_on_hand
    return total
