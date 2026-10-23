from django import template

register = template.Library()

@register.filter
def get_item(list_obj, index):
    """Get item from list by index"""
    try:
        return list_obj[index]
    except (IndexError, TypeError, KeyError):
        return True  # Default to True (posted) if error