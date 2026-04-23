import adsk.core
import adsk.fusion

from config import ATTRIBUTE_GROUP
from models import Part


def app_and_ui():
    app = adsk.core.Application.get()
    return app, app.userInterface if app else None


def selected_bodies(selection_input) -> list:
    bodies = []
    for i in range(selection_input.selectionCount):
        entity = selection_input.selection(i).entity
        body = adsk.fusion.BRepBody.cast(entity)
        if body:
            bodies.append(body)
    return bodies


def body_to_part(body: adsk.fusion.BRepBody, index: int) -> Part:
    bbox = body.boundingBox
    min_pt = bbox.minPoint
    max_pt = bbox.maxPoint
    dims = (
        abs(max_pt.x - min_pt.x) * 10.0,
        abs(max_pt.y - min_pt.y) * 10.0,
        abs(max_pt.z - min_pt.z) * 10.0,
    )
    thickness = min(dims)
    parent = body.parentComponent
    return Part(
        id=f"part_{index}",
        name=body.name,
        component_id=parent.entityToken if parent else "",
        body_id=body.entityToken,
        thickness=thickness,
        bbox_min=(min_pt.x * 10.0, min_pt.y * 10.0, min_pt.z * 10.0),
        bbox_max=(max_pt.x * 10.0, max_pt.y * 10.0, max_pt.z * 10.0),
        dimensions=dims,
    )


def attributes_for_connection(body: adsk.fusion.BRepBody, connection_id: str):
    return body.attributes.itemByName(ATTRIBUTE_GROUP, connection_id)


def write_connection_attribute(body: adsk.fusion.BRepBody, connection_id: str, value: str):
    body.attributes.add(ATTRIBUTE_GROUP, connection_id, value)


def clear_connection_attribute(body: adsk.fusion.BRepBody, connection_id: str):
    attr = attributes_for_connection(body, connection_id)
    if attr:
        attr.deleteMe()


def create_placeholder_hole_mark(body: adsk.fusion.BRepBody, name: str):
    # V1 minimal implementation: mark body metadata for generated holes.
    body.attributes.add(ATTRIBUTE_GROUP, f"hole:{name}", "generated")
