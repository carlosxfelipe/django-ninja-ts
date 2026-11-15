from threading import RLock
from typing import Annotated, Any, Literal

from ninja import Field, Path, Query, Router, Schema
from ninja.errors import HttpError
from pydantic import AfterValidator, ConfigDict, field_validator
from pydantic_core import PydanticCustomError

router = Router(tags=["Todos"])

Priority = Literal["low", "normal", "high"]
_VALID_PRIORITIES = ("low", "normal", "high")
_NOT_FOUND_RESPONSE = {"responses": {404: {"description": "Todo not found"}}}


def _validate_todo_id(value: int) -> int:
    if value < 1:
        raise PydanticCustomError(
            "value_error",
            "Todo ID must be a positive integer",
        )
    return value


def _validate_title_value(value: Any, *, required: bool) -> Any:
    if value is None:
        if required:
            raise PydanticCustomError("value_error", "Title is required")
        return None
    if value == "" and required:
        raise PydanticCustomError("value_error", "Title is required")
    if isinstance(value, str) and len(value) < 3:
        raise PydanticCustomError("value_error", "Title must be at least 3 characters")
    return value


def _validate_priority_value(
    value: Any, *, default: str | None = None, required: bool = False
) -> Any:
    if value is None or value == "":
        if required:
            raise PydanticCustomError("value_error", "Priority is required")
        return default
    if not isinstance(value, str) or value not in _VALID_PRIORITIES:
        raise PydanticCustomError(
            "value_error",
            "Priority must be low, normal, or high",
        )
    return value


TodoId = Annotated[
    int,
    AfterValidator(_validate_todo_id),
    Path(description="Todo identifier", examples=[1]),
]


class ListTodosFilters(Schema):
    done: bool | None = Field(
        default=None,
        description="Filter by completion status",
        examples=[False],
    )
    priority: Priority | None = Field(
        default=None,
        description="Filter by task priority",
        examples=["high"],
    )

    @field_validator("done", mode="before")
    @classmethod
    def normalize_done(cls, value: Any) -> Any:
        if value == "":
            return None
        return value

    @field_validator("priority", mode="before")
    @classmethod
    def validate_priority(cls, value: Any) -> Any:
        return _validate_priority_value(value, default=None, required=False)


class TodoIn(Schema):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        ...,
        min_length=3,
        description="Task title",
        examples=["Review pull requests"],
    )
    priority: Priority = Field(
        default="normal",
        description="Task priority",
        examples=["high"],
    )

    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, value: Any) -> Any:
        return _validate_title_value(value, required=True)

    @field_validator("priority", mode="before")
    @classmethod
    def validate_priority(cls, value: Any) -> Any:
        return _validate_priority_value(value, default="normal", required=False)


class TodoUpdateIn(Schema):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        ...,
        min_length=3,
        description="Task title",
        examples=["Review pull requests"],
    )
    priority: Priority = Field(
        ...,
        description="Task priority",
        examples=["high"],
    )
    done: bool = Field(
        default=False,
        description="Completion status",
        examples=[True],
    )

    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, value: Any) -> Any:
        return _validate_title_value(value, required=True)

    @field_validator("priority", mode="before")
    @classmethod
    def validate_priority(cls, value: Any) -> Any:
        return _validate_priority_value(value, required=True)


class TodoPatchIn(Schema):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(
        default=None,
        min_length=3,
        description="Updated task title",
        examples=["Deploy release v2.1"],
    )
    priority: Priority | None = Field(
        default=None,
        description="Updated task priority",
        examples=["high"],
    )
    done: bool | None = Field(
        default=None,
        description="Updated completion status",
        examples=[True],
    )

    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, value: Any) -> Any:
        return _validate_title_value(value, required=False)

    @field_validator("priority", mode="before")
    @classmethod
    def validate_priority(cls, value: Any) -> Any:
        return _validate_priority_value(value, default=None, required=False)


class TodoOut(Schema):
    id: int = Field(..., description="Todo ID", examples=[1])
    title: str = Field(..., description="Task title", examples=["Review pull requests"])
    priority: Priority = Field(
        ...,
        description="Task priority",
        examples=["normal"],
    )
    done: bool = Field(default=False, description="Completion status", examples=[False])


# In-memory store mirroring gota/examples/todos/todos.go
_STORE_LOCK = RLock()
_NEXT_ID = 3
_TODOS: list[dict[str, Any]] = [
    {
        "id": 1,
        "title": "Update README badges",
        "priority": "low",
        "done": True,
    },
    {
        "id": 2,
        "title": "Review pull requests",
        "priority": "normal",
        "done": False,
    },
    {
        "id": 3,
        "title": "Deploy release v2.0",
        "priority": "high",
        "done": False,
    },
]


@router.get(
    "",
    response=list[TodoOut],
    summary="List all todos",
    description=(
        "Returns all todo items in the store, with optional filtering by "
        "completion status and priority."
    ),
)
def list_todos(request, filters: Query[ListTodosFilters]):
    with _STORE_LOCK:
        return [
            dict(item)
            for item in _TODOS
            if (filters.done is None or item["done"] == filters.done)
            and (filters.priority is None or item["priority"] == filters.priority)
        ]


@router.get(
    "/{id}",
    response=TodoOut,
    summary="Get todo by ID",
    description="Retrieves a single todo item by its unique identifier.",
    openapi_extra=_NOT_FOUND_RESPONSE,
)
def get_todo(request, id: TodoId):
    with _STORE_LOCK:
        for item in _TODOS:
            if item["id"] == id:
                return dict(item)
    raise HttpError(404, "Todo not found")


@router.post(
    "",
    response={201: TodoOut},
    summary="Create a new todo",
    description="Validates the input payload and creates a new todo item.",
)
def create_todo(request, payload: TodoIn):
    global _NEXT_ID
    with _STORE_LOCK:
        _NEXT_ID += 1
        item = {
            "id": _NEXT_ID,
            "title": payload.title,
            "priority": payload.priority,
            "done": False,
        }
        _TODOS.append(item)
        return 201, dict(item)


@router.put(
    "/{id}",
    response=TodoOut,
    summary="Replace a todo",
    description="Validates the full payload and replaces an existing todo item.",
    openapi_extra=_NOT_FOUND_RESPONSE,
)
def update_todo(request, id: TodoId, payload: TodoUpdateIn):
    with _STORE_LOCK:
        for item in _TODOS:
            if item["id"] == id:
                item["title"] = payload.title
                item["priority"] = payload.priority
                item["done"] = payload.done
                return dict(item)
    raise HttpError(404, "Todo not found")


@router.patch(
    "/{id}",
    response=TodoOut,
    summary="Partially update a todo",
    description="Updates only the provided fields of an existing todo item.",
    openapi_extra=_NOT_FOUND_RESPONSE,
)
def patch_todo(request, id: TodoId, payload: TodoPatchIn):
    with _STORE_LOCK:
        for item in _TODOS:
            if item["id"] == id:
                if payload.title is not None:
                    item["title"] = payload.title
                if payload.priority is not None:
                    item["priority"] = payload.priority
                if payload.done is not None:
                    item["done"] = payload.done
                return dict(item)
    raise HttpError(404, "Todo not found")


@router.delete(
    "/{id}",
    response={204: None},
    summary="Delete a todo",
    description="Deletes an existing todo item by its unique identifier.",
    openapi_extra=_NOT_FOUND_RESPONSE,
)
def delete_todo(request, id: TodoId):
    with _STORE_LOCK:
        for index, item in enumerate(_TODOS):
            if item["id"] == id:
                del _TODOS[index]
                return 204, None
    raise HttpError(404, "Todo not found")
