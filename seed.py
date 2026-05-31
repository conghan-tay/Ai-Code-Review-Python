"""Populate the dev database. Run: python manage.py shell < seed.py"""
from django.contrib.auth.models import User
from inventory.models import Warehouse, Product, Order, OrderItem

Order.objects.all().delete()
Product.objects.all().delete()
Warehouse.objects.all().delete()
User.objects.filter(username="alice").delete()

alice = User.objects.create(username="alice")
wh = Warehouse.objects.create(name="Main", location="SG")
p1 = Product.objects.create(name="Widget", sku="WID-1", price_cents=1500,
                            warehouse=wh, quantity_on_hand=3)
p2 = Product.objects.create(name="Gadget", sku="GAD-1", price_cents=4200,
                            warehouse=wh, quantity_on_hand=20)

o = Order.objects.create(customer=alice)
OrderItem.objects.create(order=o, product=p1, quantity=2)
OrderItem.objects.create(order=o, product=p2, quantity=1)
print("Seeded. alice id =", alice.id, "| product ids:", p1.id, p2.id)
