from django.db import models
from django.contrib.auth.models import User


class Warehouse(models.Model):
    name = models.CharField(max_length=120)
    location = models.CharField(max_length=255)

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=64)
    price_cents = models.IntegerField(default=0)
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.CASCADE, related_name="products"
    )
    quantity_on_hand = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.name} ({self.sku})"


class Order(models.Model):
    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"
    STATUS_SHIPPED = "shipped"

    customer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="orders")
    status = models.CharField(max_length=20, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    def total_cents(self):
        total = 0
        for item in self.items.all():
            total += item.product.price_cents * item.quantity
        return total


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=1)
