from __future__ import annotations

from datetime import date, time
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=500)


class ReminderInput(BaseModel):
    remind_at: str


class TodoCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    notes: str = Field(default="", max_length=10000)
    category: str = Field(default="", max_length=100)
    priority: int = Field(default=3, ge=1, le=5)
    important: bool | None = None
    urgent: bool | None = None
    due_date: date | None = None
    due_time: time | None = None
    reminders: list[ReminderInput] = Field(default_factory=list, max_length=10)
    parent_id: int | None = None
    subtasks: list[str] = Field(default_factory=list, max_length=30)


class TodoPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    notes: str | None = Field(default=None, max_length=10000)
    category: str | None = Field(default=None, max_length=100)
    priority: int | None = Field(default=None, ge=1, le=5)
    important: bool | None = None
    urgent: bool | None = None
    due_date: date | None = None
    due_time: time | None = None
    clear_due_date: bool = False
    clear_due_time: bool = False
    clear_notes: bool = False
    clear_category: bool = False
    reminders: list[ReminderInput] | None = Field(default=None, max_length=10)
    subtasks: list[str] | None = Field(default=None, max_length=30)


class TodoSeriesCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    notes: str = Field(default="", max_length=10000)
    category: str = Field(default="", max_length=100)
    priority: int = Field(default=3, ge=1, le=5)
    frequency: Literal["daily", "weekly", "monthly"]
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    start_date: date
    end_date: date
    month_day: int | None = Field(default=None, ge=1, le=31)
    due_time: time | None = None
    important: bool | None = None
    urgent: bool | None = None
    reminder_enabled: bool = True
    reminder_times: list[time] = Field(default_factory=list, max_length=10)
    subtasks: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_recurrence(self) -> "TodoSeriesCreate":
        if self.frequency == "weekly" and not self.weekdays:
            raise ValueError("每周重复需要至少选择一个星期")
        if any(day < 1 or day > 7 for day in self.weekdays):
            raise ValueError("星期必须在1到7之间")
        if self.frequency != "weekly" and self.weekdays:
            raise ValueError("每日或每月重复不需要指定星期")
        if self.frequency == "monthly" and self.month_day is None:
            raise ValueError("每月重复需要指定日期")
        if self.frequency != "monthly" and self.month_day is not None:
            raise ValueError("只有每月重复需要指定日期")
        if self.end_date < self.start_date:
            raise ValueError("重复结束日期不能早于开始日期")
        return self


class TodoSeriesPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    notes: str | None = Field(default=None, max_length=10000)
    category: str | None = Field(default=None, max_length=100)
    priority: int | None = Field(default=None, ge=1, le=5)
    frequency: Literal["daily", "weekly", "monthly"] | None = None
    weekdays: list[int] | None = Field(default=None, max_length=7)
    start_date: date | None = None
    end_date: date | None = None
    month_day: int | None = Field(default=None, ge=1, le=31)
    due_time: time | None = None
    important: bool | None = None
    urgent: bool | None = None
    reminder_enabled: bool | None = None
    reminder_times: list[time] | None = Field(default=None, max_length=10)
    subtasks: list[str] | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def validate_recurrence_patch(self) -> "TodoSeriesPatch":
        if self.weekdays is not None and any(day < 1 or day > 7 for day in self.weekdays):
            raise ValueError("星期必须在1到7之间")
        if self.frequency == "weekly" and self.weekdays == []:
            raise ValueError("每周重复需要至少选择一个星期")
        if self.frequency == "weekly" and self.weekdays is None:
            raise ValueError("修改为每周重复时需要指定星期")
        if self.frequency in {"daily", "monthly"} and self.weekdays:
            raise ValueError("每日或每月重复不需要指定星期")
        if self.frequency == "monthly" and self.month_day is None:
            raise ValueError("每月重复需要指定日期")
        if self.frequency in {"daily", "weekly"} and self.month_day is not None:
            raise ValueError("每日或每周重复不需要指定每月日期")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("重复结束日期不能早于开始日期")
        return self


class ScheduleEventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    notes: str = Field(default="", max_length=10000)
    frequency: Literal["once", "weekly"] = "once"
    event_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    start_period: int | None = Field(default=None, ge=1, le=14)
    end_period: int | None = Field(default=None, ge=1, le=14)
    start_time: time | None = None
    end_time: time | None = None

    @model_validator(mode="after")
    def validate_event(self) -> "ScheduleEventCreate":
        if self.frequency == "once":
            if self.event_date is None:
                raise ValueError("单次安排需要提供日期")
            if self.weekdays:
                raise ValueError("单次安排不需要指定星期")
        else:
            if self.start_date is None or not self.weekdays:
                raise ValueError("每周安排需要开始日期和星期")
            if any(day < 1 or day > 7 for day in self.weekdays):
                raise ValueError("星期必须在1到7之间")
            if self.event_date is not None:
                raise ValueError("每周安排请使用开始日期")
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValueError("重复结束日期不能早于开始日期")
        uses_periods = self.start_period is not None or self.end_period is not None
        uses_clock = self.start_time is not None or self.end_time is not None
        if uses_periods and uses_clock:
            raise ValueError("请使用节次或具体时间其中一种方式")
        if uses_periods and (self.start_period is None or self.end_period is None):
            raise ValueError("开始和结束节次需要同时填写")
        if uses_clock and (self.start_time is None or self.end_time is None):
            raise ValueError("开始和结束时间需要同时填写")
        if not uses_periods and not uses_clock:
            raise ValueError("请填写节次或具体时间")
        if self.start_period and self.end_period and self.end_period < self.start_period:
            raise ValueError("结束节次不能早于开始节次")
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValueError("结束时间必须晚于开始时间")
        return self


class ScheduleEventPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    notes: str | None = Field(default=None, max_length=10000)
    frequency: Literal["once", "weekly"] | None = None
    event_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    weekdays: list[int] | None = Field(default=None, max_length=7)
    start_period: int | None = Field(default=None, ge=1, le=14)
    end_period: int | None = Field(default=None, ge=1, le=14)
    start_time: time | None = None
    end_time: time | None = None


class CoursePatch(BaseModel):
    course_name: str | None = Field(default=None, min_length=1, max_length=300)
    weekday: int | None = Field(default=None, ge=1, le=7)
    start_period: int | None = Field(default=None, ge=1, le=30)
    end_period: int | None = Field(default=None, ge=1, le=30)
    start_time: time | None = None
    end_time: time | None = None
    weeks: list[int] | None = Field(default=None, max_length=40)
    week_parity: Literal["all", "odd", "even"] | None = None
    location: str | None = Field(default=None, max_length=300)
    teacher: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)
    reminder_enabled: bool | None = None
    reminder_lead_minutes: int | None = Field(default=None, ge=0, le=180)


class CourseCreate(BaseModel):
    term_id: int = Field(gt=0)
    course_name: str = Field(min_length=1, max_length=300)
    weekday: int = Field(ge=1, le=7)
    start_period: int | None = Field(default=None, ge=1, le=30)
    end_period: int | None = Field(default=None, ge=1, le=30)
    start_time: time | None = None
    end_time: time | None = None
    weeks: list[int] = Field(default_factory=list, max_length=40)
    week_parity: Literal["all", "odd", "even"] = "all"
    location: str = Field(default="", max_length=300)
    teacher: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=1000)
    reminder_enabled: bool = False
    reminder_lead_minutes: int = Field(default=10, ge=0, le=180)


class CourseOccurrencePatch(BaseModel):
    action: Literal["cancelled", "override"]
    start_period: int | None = Field(default=None, ge=1, le=30)
    end_period: int | None = Field(default=None, ge=1, le=30)
    start_time: time | None = None
    end_time: time | None = None
    location: str | None = Field(default=None, max_length=300)
    teacher: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)


class TermPatch(BaseModel):
    end_date: date


class CourseReminderPreview(BaseModel):
    term_id: int | None = Field(default=None, gt=0)
    start_periods: list[int] = Field(default_factory=list, max_length=14)
    course_ids: list[int] = Field(default_factory=list, max_length=1000)
    enabled: bool = True
    lead_minutes: int = Field(default=10, ge=0, le=180)
    umo: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_target(self) -> "CourseReminderPreview":
        if not self.start_periods and not self.course_ids:
            raise ValueError("请指定开始节次或课程编号")
        if any(period < 1 or period > 30 for period in self.start_periods):
            raise ValueError("开始节次范围无效")
        return self


class CourseReminderApply(BaseModel):
    preview_id: str = Field(default="", max_length=100)
    umo: str = Field(default="", max_length=1000)
    confirmed: bool = False


class ReminderSchedulesPatch(BaseModel):
    daily_brief_enabled: bool | None = None
    daily_brief_time: time | None = None
    weekly_review_enabled: bool | None = None
    weekly_review_weekday: int | None = Field(default=None, ge=1, le=7)
    weekly_review_time: time | None = None


class WeeklyReviewPut(BaseModel):
    reflection: str = Field(default="", max_length=20000)


class ReminderCreate(BaseModel):
    todo_id: int | None = None
    title: str = Field(min_length=1, max_length=300)
    remind_at: str
    recipient_umo: str = Field(default="", max_length=1000)


class SessionBind(BaseModel):
    umo: str = Field(min_length=1, max_length=1000)


class CourseInput(BaseModel):
    course_name: str = Field(min_length=1, max_length=300)
    weekday: int = Field(ge=1, le=7)
    start_period: int | None = Field(default=None, ge=1, le=30)
    end_period: int | None = Field(default=None, ge=1, le=30)
    start_time: time | None = None
    end_time: time | None = None
    weeks: list[int] = Field(default_factory=list, max_length=40)
    week_parity: Literal["all", "odd", "even"] = "all"
    location: str = Field(default="", max_length=300)
    teacher: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_period_range(self) -> "CourseInput":
        uses_periods = self.start_period is not None or self.end_period is not None
        uses_times = self.start_time is not None or self.end_time is not None
        if uses_periods and (self.start_period is None or self.end_period is None):
            raise ValueError("开始和结束节次需要同时填写")
        if uses_times and (self.start_time is None or self.end_time is None):
            raise ValueError("开始和结束时间需要同时填写")
        if not uses_periods and not uses_times:
            raise ValueError("课程需要填写节次或开始/结束时间")
        if self.start_period is not None and self.end_period is not None and self.end_period < self.start_period:
            raise ValueError("end_period must be greater than or equal to start_period")
        if self.start_time is not None and self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("结束时间必须晚于开始时间")
        if any(week < 1 or week > 40 for week in self.weeks):
            raise ValueError("周次必须在1到40之间")
        return self


class CourseImportCommit(BaseModel):
    term_name: str = Field(min_length=1, max_length=100)
    week1_monday: date
    end_date: date
    courses: list[CourseInput] = Field(min_length=1, max_length=1000)
    replace_existing: bool = False

    @model_validator(mode="after")
    def validate_term(self) -> "CourseImportCommit":
        if self.week1_monday.isoweekday() != 1:
            raise ValueError("第1周日期必须是周一")
        if self.end_date < self.week1_monday:
            raise ValueError("学期结束日期不能早于第1周周一")
        return self


class ReminderRetry(BaseModel):
    confirm: bool = False


class BulkDeleteRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    confirm: bool = False
