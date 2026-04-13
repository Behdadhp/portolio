from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def query_string(context, **kwargs):
    """
    Builds a query string from the current request's GET params,
    overriding with any provided kwargs.
    Usage: {% query_string page=3 per_page=20 %}
    """
    request = context["request"]
    params = request.GET.copy()
    for key, value in kwargs.items():
        params[key] = value
    return "?" + params.urlencode()
