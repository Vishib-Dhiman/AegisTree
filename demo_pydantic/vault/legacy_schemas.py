"""Legacy schema serialization using Pydantic v1 dict."""


def legacy_serialize(model):
    return model.dict()
