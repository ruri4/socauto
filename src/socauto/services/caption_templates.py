"""Caption template validation and literal placeholder rendering."""

MAX_CAPTION_UNITS = 2200
_PLACEHOLDER = "{{caption}}"


class CaptionTemplateError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def utf16_units(value: str) -> int:
    try:
        return len(value.encode("utf-16-le")) // 2
    except UnicodeEncodeError:
        raise CaptionTemplateError("caption_template_invalid") from None


def validate_template_body(value: str) -> str:
    if utf16_units(value) > MAX_CAPTION_UNITS:
        raise CaptionTemplateError("caption_template_too_long")
    position = 0
    while position < len(value):
        opening = value.find("{{", position)
        closing = value.find("}}", position)
        if opening == -1 and closing == -1:
            break
        if opening == -1 or (closing != -1 and closing < opening):
            raise CaptionTemplateError("caption_template_invalid")
        end = value.find("}}", opening + 2)
        if end == -1 or value[opening : end + 2] != _PLACEHOLDER:
            raise CaptionTemplateError("caption_template_invalid")
        position = end + 2
    return value


def render_template(template: str, source_caption: str) -> str:
    validate_template_body(template)
    rendered = template.replace(_PLACEHOLDER, source_caption)
    if utf16_units(rendered) > MAX_CAPTION_UNITS:
        raise CaptionTemplateError("caption_rendered_too_long")
    return rendered
