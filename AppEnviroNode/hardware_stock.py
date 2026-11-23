
"""Admin-only stock adjustments for existing U-Node catalog products.

This module is intentionally separate from the large legacy views.py file.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .models import Product, SystemLog

MAX_STOCK = 1_000_000


@login_required
@require_POST
def hardware_stock_update(request, product_id):
    """Add stock or replace an exact count without changing product identity."""
    user = request.user
    if not (user.is_superuser or (getattr(user, 'role', None) == 'admin' and user.is_approved)):
        return HttpResponseForbidden('Only EnviroPlus administrators can adjust hardware inventory.')

    operation = request.POST.get('stock_operation', '').strip()
    quantity_text = request.POST.get('quantity', '').strip()

    if operation not in ('add', 'set'):
        messages.error(request, 'Choose a valid stock adjustment type.')
        return redirect('app:hardware_inventory')

    if not quantity_text.isascii() or not quantity_text.isdigit():
        messages.error(request, 'Stock quantity must be a non-negative whole number.')
        return redirect('app:hardware_inventory')

    quantity = int(quantity_text)
    if quantity > MAX_STOCK or (operation == 'add' and quantity == 0):
        messages.error(request, f'Enter a valid quantity (maximum {MAX_STOCK:,}; additions must be at least 1).')
        return redirect('app:hardware_inventory')

    with transaction.atomic():
        product = get_object_or_404(Product.objects.select_for_update(), pk=product_id)
        old_stock = product.stock

        if operation == 'set':
            expected_text = request.POST.get('expected_stock', '').strip()
            if not expected_text.lstrip('-').isdigit() or int(expected_text) != old_stock:
                messages.error(request, f'{product.name} stock has changed since you opened the form. Refresh and try again.')
                return redirect('app:hardware_inventory')
            new_stock = quantity
        else:
            new_stock = old_stock + quantity
            if new_stock > MAX_STOCK:
                messages.error(request, f'The resulting stock cannot exceed {MAX_STOCK:,} units.')
                return redirect('app:hardware_inventory')

        product.stock = new_stock
        product.save(update_fields=['stock'])

        admin_name = user.get_full_name() or user.username
        action_text = f'added {quantity} unit(s)' if operation == 'add' else 'set the exact stock'
        SystemLog.objects.create(
            event_type='admin',
            severity='good',
            message=(
                f'Admin {admin_name} {action_text} for hardware {product.name} '
                f'(product ID {product.pk}): {old_stock} -> {new_stock} units.'
            ),
        )

    messages.success(request, f'{product.name} stock updated: {old_stock} → {new_stock} units.')
    return redirect('app:hardware_inventory')
