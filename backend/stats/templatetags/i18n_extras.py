from __future__ import annotations

from django import template

from stats.i18n_map import tr as tr_map

register = template.Library()


@register.simple_tag
def tr(text: str) -> str:
    return tr_map(text)
