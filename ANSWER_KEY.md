# ANSWER KEY — don't open until you've done your own review

Bugs are grouped by **severity**, because triage is the skill being tested.
In the real round: name the high-severity ones first, then pick 1–2 to fix
cleanly. A 🎯 marks the ones that make the strongest fix choices.

---

## HIGH severity (correctness / concurrency / security / data loss)

### 1. 🎯 Race condition on stock decrement — `views.place_order`
```python
product.quantity_on_hand = product.quantity_on_hand - 1
product.save()
```
Read-modify-write in Python. Two concurrent orders read the same value and
one decrement is lost — oversell. **Fix:** `F()` expression
(`F("quantity_on_hand") - 1`) so the DB does it atomically, ideally inside
`transaction.atomic()` with `select_for_update()`. This is the centerpiece
bug for a Django review round and the best fix to showcase.

### 2. 🎯 No transaction around order creation — `views.place_order`
The order is created, stock is decremented in a loop, then status is set to
PAID — across many separate writes with no `transaction.atomic()`. If any
`Product.objects.get(pk=pid)` raises (bad id) mid-loop, you get a half-built
order with some stock already decremented. **Fix:** wrap the whole operation
in `transaction.atomic()`. Pairs naturally with #1 as one clean fix.

### 3. Same race condition on restock — `views.restock_product`
`product.quantity_on_hand = product.quantity_on_hand + amount` then save().
Same read-modify-write problem. Same `F()` fix.

### 4. Stock can go negative / no validation — `views.place_order`
Nothing checks `quantity_on_hand > 0` before decrementing, and quantity is
hardcoded to 1 regardless of what was requested. Overselling is allowed.

### 5. Silent exception swallowing — `views.cancel_order`
```python
except Exception:
    pass
```
If returning items to stock fails, the order is still reported cancelled and
the error vanishes. Also: stock is restored but if `order.delete()` runs
after a partial failure, state is inconsistent. **Fix:** wrap in
`transaction.atomic()`, don't swallow — let it raise or handle specifically.

### 6. Hardcoded SECRET_KEY + DEBUG=True + ALLOWED_HOSTS=["*"] — `config/settings.py`
Secret committed to source; debug on in what looks like a shared config.
Security-company interviewers will care. **Fix:** read from env
(`os.environ`), default DEBUG to False.

---

## MEDIUM severity (performance / Python correctness)

### 7. 🎯 N+1 queries — `views.order_summary`
Loops over orders, then `order.items.all()`, then `item.product` and
`item.product.warehouse` per item. One query per relation per row. **Fix:**
`Order.objects.filter(...).prefetch_related("items__product__warehouse")`.
Clean, self-contained, easy to show a before/after query count — a strong
alternative fix to the race condition if you'd rather demo performance.

### 8. N+1 in `total_cents()` — `models.Order`
`for item in self.items.all(): item.product.price_cents` hits the DB per
item. Called once per order inside the summary loop, compounding #7.

### 9. Mutable default argument — `views.add_tags`
```python
def add_tags(request, product_id, tags=[]):
```
The list is shared across all calls — tags leak between requests/products.
Classic Python gotcha. **Fix:** `tags=None` then `tags = tags or []`.

### 10. Late-binding closure in loop — `services.build_warehouse_index`
```python
index[w.name] = lambda: w.products.count()
```
Every lambda captures the same `w`; all return the last warehouse's count.
**Fix:** `lambda w=w: w.products.count()` (default-arg capture).

### 11. Reference copy, not a copy — `services.clone_product_template`
```python
new_product = template
new_product["sku"] = ...
```
Mutates the caller's original dict; "clone" is a lie. **Fix:**
`copy.deepcopy(template)` (copy is already imported, a deliberate hint).

---

## LOW severity (style / minor correctness — mention briefly, don't fix)

### 12. `is`/`==` and type bug — `views.find_low_stock`
- `if threshold == None:` should be `is None`.
- Bigger: `threshold` from `request.GET` is a **string**; comparing
  `product.quantity_on_hand < threshold` (int < str) raises TypeError in
  Py3 when threshold is provided. Needs `int(...)`. (Arguably MEDIUM.)

### 13. Module-level mutable cache — `views.add_tags` / `PRODUCT_TAG_CACHE`
Global dict as a cache; also defined *after* the function that uses it
(works because it's called at request time, but it's confusing). Not
thread-safe, lost on restart. Worth naming as a design smell.

### 14. `apply_bulk_discount` rounding — `services.py`
`int(new_price)` truncates rather than rounds; minor money bug.

### 15. Missing auth — every view
No `@login_required` / permission checks; any caller can restock, cancel,
or read another customer's orders. Depending on framing, this is HIGH at a
security company — worth raising even if you don't fix it.

---

## How to play this in the interview

- **Review phase:** rattle off the HIGH ones with a one-line "why it
  matters" each. Show you can see the whole board. Group them
  ("there's a family of read-modify-write race conditions in
  place_order, restock, and cancel").
- **Triage:** "The race condition in `place_order` is the one I'd fix first
  — it causes overselling, which is real money, and it's the kind of bug
  that's invisible until you're under load."
- **Fix phase — pick ONE cleanly.** Best showcase is #1 + #2 together:
  `transaction.atomic()` + `select_for_update()` + `F()` + a stock-check
  guard for the negative-quantity edge case. That single fix touches
  concurrency, transactions, AND edge handling — exactly the "improve
  overall quality" bar. Then write a test that fails before / passes after.
- Mention the others exist; don't gold-plate. Stopping cleanly is a signal.
