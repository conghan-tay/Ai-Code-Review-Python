from django.urls import path

from . import views

urlpatterns = [
    path("products/<int:product_id>/restock/", views.restock_product),
    path("products/<int:product_id>/tags/", views.add_tags),
    path("products/low-stock/", views.find_low_stock),
    path("customers/<int:customer_id>/orders/", views.order_summary),
    path("customers/<int:customer_id>/place-order/", views.place_order),
    path("orders/<int:order_id>/cancel/", views.cancel_order),
]
