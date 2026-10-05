from behive.engine.entity_remap import remap_entity_type


def test_remap_person_geo_org_noise():
    assert remap_entity_type("PERSON", "United States") == "location"
    assert remap_entity_type("PERSON", "European Union") == "organization"
    assert remap_entity_type("PERSON", "Helvetica Neue") == "noise"
    assert remap_entity_type("PERSON", "Jane Doe") == "person"
    assert remap_entity_type("ORG", "OpenAI") == "organization"
