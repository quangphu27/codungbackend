from datetime import datetime, timezone
from bson import ObjectId


def utc_now():
    return datetime.now(timezone.utc)


def serialize_doc(doc):
    if doc is None:
        return None
    if isinstance(doc, ObjectId):
        return str(doc)
    if isinstance(doc, datetime):
        return doc.isoformat()
    if isinstance(doc, list):
        return [serialize_doc(d) for d in doc]
    if isinstance(doc, dict):
        result = {}
        for key, value in doc.items():
            if isinstance(value, ObjectId):
                result[key] = str(value)
            elif isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, dict):
                result[key] = serialize_doc(value)
            elif isinstance(value, list):
                result[key] = serialize_doc(value)
            else:
                result[key] = value
        if "_id" in result:
            result["id"] = result.pop("_id")
        return result
    return doc


def to_object_id(id_str):
    if not id_str:
        return None
    try:
        return ObjectId(id_str)
    except Exception:
        return None
