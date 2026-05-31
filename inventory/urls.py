from django.urls import path

from . import views

urlpatterns = [
    path("products/<int:product_id>/restock/", views.restock_product),
    path("products/<int:product_id>/tags/", views.add_tags),
    path("products/<int:product_id>/clone/", views.clone_product),
    path("products/low-stock/", views.find_low_stock),
    path("products/bulk-discount/", views.bulk_discount_preview),
    path("customers/<int:customer_id>/orders/", views.order_summary),
    path("customers/<int:customer_id>/place-order/", views.place_order),
    path("orders/<int:order_id>/cancel/", views.cancel_order),
    path("warehouses/", views.warehouse_summary),
]
