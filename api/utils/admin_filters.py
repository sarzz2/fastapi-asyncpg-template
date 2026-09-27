"""
Reusable Starlette-Admin filter classes, registries, and datetime parsing utilities.
"""

from datetime import datetime, time, timezone
from typing import Any, ClassVar

from starlette_admin.fields import DateTimeField, StringField, UUIDField
from starlette_admin.filters import BaseFilter, FilterApplyContext, FilterDataType, FilterRegistry, FilterRule


def parse_admin_datetime(val: Any, is_end: bool = False) -> datetime:
    """Parse datetime from object or ISO string, handling date-only strings."""
    if isinstance(val, datetime):
        dt = val
    else:
        s = str(val).strip()
        if len(s) == 10 and "T" not in s and " " not in s:
            d = datetime.fromisoformat(s).date()
            dt = datetime.combine(d, time.max if is_end else time.min)
        else:
            dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def extract_date_range(rule: FilterRule) -> tuple[datetime | None, datetime | None]:
    """Extract start and end datetimes from a FilterRule."""
    start: datetime | None = None
    end: datetime | None = None
    if rule.filter in ("gte", "gt") and rule.value:
        start = parse_admin_datetime(rule.value, is_end=False)
    elif rule.filter in ("lte", "lt") and rule.value:
        end = parse_admin_datetime(rule.value, is_end=True)
    elif rule.filter == "between":
        if rule.value:
            start = parse_admin_datetime(rule.value, is_end=False)
        if getattr(rule, "value2", None):
            end = parse_admin_datetime(rule.value2, is_end=True)
    elif rule.filter == "eq" and rule.value:
        start = parse_admin_datetime(rule.value, is_end=False)
        end = parse_admin_datetime(rule.value, is_end=True)
    return start, end


class DateBetweenFilter(BaseFilter):
    """Filter for dates between two boundaries."""

    name: ClassVar[str] = "between"
    label: ClassVar[str] = "Between"
    data_type: ClassVar[FilterDataType] = FilterDataType.DATE
    has_value2: ClassVar[bool] = True

    def apply(self, ctx: FilterApplyContext) -> Any:
        return ctx.query


class DateGteFilter(BaseFilter):
    """Filter for dates greater than or equal to value."""

    name: ClassVar[str] = "gte"
    label: ClassVar[str] = "After or On (>=)"
    data_type: ClassVar[FilterDataType] = FilterDataType.DATE

    def apply(self, ctx: FilterApplyContext) -> Any:
        return ctx.query


class DateLteFilter(BaseFilter):
    """Filter for dates less than or equal to value."""

    name: ClassVar[str] = "lte"
    label: ClassVar[str] = "Before or On (<=)"
    data_type: ClassVar[FilterDataType] = FilterDataType.DATE

    def apply(self, ctx: FilterApplyContext) -> Any:
        return ctx.query


class DateEqualFilter(BaseFilter):
    """Filter for dates equal to value."""

    name: ClassVar[str] = "eq"
    label: ClassVar[str] = "On Date (=)"
    data_type: ClassVar[FilterDataType] = FilterDataType.DATE

    def apply(self, ctx: FilterApplyContext) -> Any:
        return ctx.query


class StringEqualFilter(BaseFilter):
    """Filter for exact string equality."""

    name: ClassVar[str] = "eq"
    label: ClassVar[str] = "Equals"
    data_type: ClassVar[FilterDataType] = FilterDataType.STRING

    def apply(self, ctx: FilterApplyContext) -> Any:
        return ctx.query


class StringContainsFilter(BaseFilter):
    """Filter for string substring match."""

    name: ClassVar[str] = "contains"
    label: ClassVar[str] = "Contains"
    data_type: ClassVar[FilterDataType] = FilterDataType.STRING

    def apply(self, ctx: FilterApplyContext) -> Any:
        return ctx.query


DEFAULT_FILTER_REGISTRY = FilterRegistry()
DEFAULT_FILTER_REGISTRY.register(
    DateTimeField,
    DateBetweenFilter,
    DateGteFilter,
    DateLteFilter,
    DateEqualFilter,
)
DEFAULT_FILTER_REGISTRY.register(StringField, StringContainsFilter, StringEqualFilter)
DEFAULT_FILTER_REGISTRY.register(UUIDField, StringEqualFilter)
