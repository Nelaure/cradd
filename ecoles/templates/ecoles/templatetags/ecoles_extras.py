from django import template

register = template.Library()

@register.filter
def startswith(value, arg):
    """Vérifie si une chaîne commence par une sous-chaîne."""
    if isinstance(value, str):
        return value.startswith(arg)
    return False