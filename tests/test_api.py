import asyncio
import base64
import io
from typing import Any

import pytest
from PIL import Image

from tests.conftest import PASSWORD, GraphQL, sample_document

pytestmark = pytest.mark.anyio

CREATE = """
mutation($input: CreatePatternInput!) {
  createPattern(input: $input) { id name material currentVersion }
}
"""
SAVE = """
mutation($input: SavePatternInput!) {
  savePattern(input: $input) { id currentVersion }
}
"""
PATTERN = """
query($id: ID!, $version: Int) {
  pattern(id: $id) { name currentVersion document(version: $version) versions { number note shapeCount } }
}
"""


def _code(body: dict[str, Any]) -> str:
    return str(body["errors"][0]["extensions"]["code"])


async def _create(gql: GraphQL, token: str, shapes: int = 3) -> str:
    body = await gql(
        CREATE,
        token,
        input={"name": "Mochila wayuu", "material": "fabric", "document": sample_document(shapes)},
    )
    return str(body["data"]["createPattern"]["id"])


async def test_health_and_status(api) -> None:  # noqa: ANN001
    assert (await api.get("/healthz")).json() == {"status": "ok"}
    status = (await api.get("/status")).json()
    assert status["databaseOk"] is True


async def test_register_login_and_me(gql: GraphQL, make_user) -> None:  # noqa: ANN001
    await make_user("rosa@example.com")
    body = await gql(
        "mutation($e: String!, $p: String!) { login(email: $e, password: $p) { token user { email } } }",
        e="ROSA@example.com ",
        p=PASSWORD,
    )
    token = body["data"]["login"]["token"]
    me = await gql("{ me { email fullName craft } }", token)
    assert me["data"]["me"] == {
        "email": "rosa@example.com",
        "fullName": "Rosa Ortiz",
        "craft": "tejido",
    }


async def test_duplicate_email_and_wrong_password(gql: GraphQL, make_user) -> None:  # noqa: ANN001
    await make_user("rosa@example.com")
    again = await gql(
        "mutation($i: RegisterInput!) { register(input: $i) { token } }",
        i={"email": "rosa@example.com", "password": PASSWORD, "fullName": "Otra"},
    )
    assert _code(again) == "EMAIL_TAKEN"
    wrong = await gql(
        'mutation { login(email: "rosa@example.com", password: "nope-nope") { token } }'
    )
    unknown = await gql(
        'mutation { login(email: "nadie@example.com", password: "nope-nope") { token } }'
    )
    assert _code(wrong) == _code(unknown) == "INVALID_CREDENTIALS"
    assert wrong["errors"][0]["message"] == unknown["errors"][0]["message"]


async def test_everything_requires_a_session(gql: GraphQL) -> None:
    assert _code(await gql("{ patterns { id } }")) == "UNAUTHENTICATED"
    assert _code(await gql("{ me { id } }", "forged.token.value")) == "UNAUTHENTICATED"


async def test_create_save_and_read_versions(gql: GraphQL, make_user) -> None:  # noqa: ANN001
    token = await make_user("rosa@example.com")
    pattern_id = await _create(gql, token)

    saved = await gql(
        SAVE,
        token,
        input={
            "id": pattern_id,
            "baseVersion": 1,
            "document": sample_document(5),
            "note": "Más hojas",
        },
    )
    assert saved["data"]["savePattern"]["currentVersion"] == 2

    body = await gql(PATTERN, token, id=pattern_id)
    pattern = body["data"]["pattern"]
    assert pattern["currentVersion"] == 2
    assert len(pattern["document"]["shapes"]) == 5
    assert pattern["versions"] == [
        {"number": 2, "note": "Más hojas", "shapeCount": 5},
        {"number": 1, "note": "Versión inicial", "shapeCount": 3},
    ]
    old = await gql(PATTERN, token, id=pattern_id, version=1)
    assert len(old["data"]["pattern"]["document"]["shapes"]) == 3


async def test_stale_save_is_a_conflict(gql: GraphQL, make_user) -> None:  # noqa: ANN001
    token = await make_user("rosa@example.com")
    pattern_id = await _create(gql, token)
    await gql(
        SAVE, token, input={"id": pattern_id, "baseVersion": 1, "document": sample_document(4)}
    )
    stale = await gql(
        SAVE, token, input={"id": pattern_id, "baseVersion": 1, "document": sample_document(2)}
    )
    assert _code(stale) == "VERSION_CONFLICT"
    assert stale["errors"][0]["extensions"]["currentVersion"] == 2


async def test_concurrent_saves_from_the_same_version_keep_only_one(
    gql: GraphQL, make_user
) -> None:  # noqa: ANN001
    token = await make_user("rosa@example.com")
    pattern_id = await _create(gql, token)
    results = await asyncio.gather(
        *(
            gql(
                SAVE,
                token,
                input={"id": pattern_id, "baseVersion": 1, "document": sample_document(n)},
            )
            for n in (2, 4, 6)
        )
    )
    winners = [r for r in results if "errors" not in r]
    assert len(winners) == 1
    assert all(_code(r) == "VERSION_CONFLICT" for r in results if "errors" in r)
    body = await gql(PATTERN, token, id=pattern_id)
    assert body["data"]["pattern"]["currentVersion"] == 2


async def test_restore_creates_a_new_version(gql: GraphQL, make_user) -> None:  # noqa: ANN001
    token = await make_user("rosa@example.com")
    pattern_id = await _create(gql, token)
    await gql(
        SAVE, token, input={"id": pattern_id, "baseVersion": 1, "document": sample_document(6)}
    )
    restored = await gql(
        "mutation($id: ID!) { restoreVersion(id: $id, number: 1, baseVersion: 2) { currentVersion } }",
        token,
        id=pattern_id,
    )
    assert restored["data"]["restoreVersion"]["currentVersion"] == 3
    body = await gql(PATTERN, token, id=pattern_id)
    assert len(body["data"]["pattern"]["document"]["shapes"]) == 3
    assert body["data"]["pattern"]["versions"][0]["note"] == "Restaurada desde la versión 1"


async def test_patterns_are_private(gql: GraphQL, make_user) -> None:  # noqa: ANN001
    rosa = await make_user("rosa@example.com")
    luis = await make_user("luis@example.com")
    pattern_id = await _create(gql, rosa)
    assert _code(await gql(PATTERN, luis, id=pattern_id)) == "NOT_FOUND"
    hijack = await gql(
        SAVE, luis, input={"id": pattern_id, "baseVersion": 1, "document": sample_document(1)}
    )
    assert _code(hijack) == "NOT_FOUND"
    assert (await gql("{ patterns { id } }", luis))["data"]["patterns"] == []
    deleted = await gql("mutation($id: ID!) { deletePattern(id: $id) }", luis, id=pattern_id)
    assert _code(deleted) == "NOT_FOUND"


async def test_invalid_documents_are_explained(gql: GraphQL, make_user) -> None:  # noqa: ANN001
    token = await make_user("rosa@example.com")
    document = sample_document(1)
    document["shapes"][0]["fill"] = "red"
    body = await gql(CREATE, token, input={"name": "X", "material": "fabric", "document": document})
    assert _code(body) == "INVALID_DOCUMENT"
    assert "shapes.0.fill" in body["errors"][0]["extensions"]["problems"][0]
    bad_material = await gql(
        CREATE, token, input={"name": "X", "material": "gold", "document": sample_document(1)}
    )
    assert _code(bad_material) == "INVALID_MATERIAL"


async def test_rename_and_delete(gql: GraphQL, make_user) -> None:  # noqa: ANN001
    token = await make_user("rosa@example.com")
    pattern_id = await _create(gql, token)
    renamed = await gql(
        'mutation($id: ID!) { renamePattern(id: $id, name: " Cojín ") { name } }',
        token,
        id=pattern_id,
    )
    assert renamed["data"]["renamePattern"]["name"] == "Cojín"
    assert (await gql("mutation($id: ID!) { deletePattern(id: $id) }", token, id=pattern_id))[
        "data"
    ] == {"deletePattern": True}
    assert (await gql("{ patterns { id } }", token))["data"]["patterns"] == []


async def test_ai_tools_through_graphql(gql: GraphQL, make_user) -> None:  # noqa: ANN001
    token = await make_user("rosa@example.com")
    image = Image.new("RGB", (40, 20), (30, 60, 140))
    image.paste((230, 200, 60), (20, 0, 40, 20))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()

    palette = await gql(
        "mutation($img: String!) { extractPalette(image: $img, colors: 2) { hex share } }",
        token,
        img=data_url,
    )
    colors = [c["hex"] for c in palette["data"]["extractPalette"]]
    assert sorted(colors) == ["#1e3c8c", "#e6c83c"]

    variations = await gql(
        """mutation($doc: JSON!, $pal: [String!]!) {
             generateVariations(document: $doc, palette: $pal, count: 2) {
               original { total } variations { score { total contrast } document }
             }
           }""",
        token,
        doc=sample_document(6),
        pal=colors,
    )
    result = variations["data"]["generateVariations"]
    assert len(result["variations"]) == 2
    assert result["variations"][0]["score"]["total"] >= result["original"]["total"]

    layout = await gql(
        """mutation($doc: JSON!) {
             optimizeLayout(document: $doc, rollWidth: 250) {
               wastePercent baselineWastePercent cutOrder placements { shapeId rotated }
             }
           }""",
        token,
        doc=sample_document(6),
    )
    nest = layout["data"]["optimizeLayout"]
    assert len(nest["placements"]) == 6
    assert nest["wastePercent"] <= nest["baselineWastePercent"]


async def test_bad_palette_is_rejected(gql: GraphQL, make_user) -> None:  # noqa: ANN001
    token = await make_user("rosa@example.com")
    body = await gql(
        'mutation($doc: JSON!) { generateVariations(document: $doc, palette: ["blue"]) { original { total } } }',
        token,
        doc=sample_document(2),
    )
    assert _code(body) == "INVALID_PALETTE"


async def test_deep_queries_are_rejected(gql: GraphQL) -> None:
    deep = "{ __schema { types " + "{ fields { type " * 6 + "{ name }" + " } }" * 6 + " } }"
    body = await gql(deep)
    assert "depth" in body["errors"][0]["message"].lower()


async def test_saving_can_change_the_material(gql: GraphQL, make_user) -> None:  # noqa: ANN001
    token = await make_user("rosa@example.com")
    pattern_id = await _create(gql, token)
    await gql(
        SAVE,
        token,
        input={
            "id": pattern_id,
            "baseVersion": 1,
            "document": sample_document(2),
            "material": "leather",
        },
    )
    body = await gql("query($id: ID!) { pattern(id: $id) { material } }", token, id=pattern_id)
    assert body["data"]["pattern"]["material"] == "leather"
    wrong = await gql(
        SAVE,
        token,
        input={
            "id": pattern_id,
            "baseVersion": 2,
            "document": sample_document(2),
            "material": "gold",
        },
    )
    assert _code(wrong) == "INVALID_MATERIAL"


async def test_documents_are_always_returned_as_v2(gql: GraphQL, make_user) -> None:  # noqa: ANN001
    token = await make_user("rosa@example.com")
    pattern_id = await _create(gql, token)  # sends a v1 document
    body = await gql(PATTERN, token, id=pattern_id)
    document = body["data"]["pattern"]["document"]
    assert document["schemaVersion"] == 2 and document["mode"] == "pattern"
    assert document["shapes"][0]["layerId"] is None


async def test_paths_with_too_many_points_are_rejected(gql: GraphQL, make_user) -> None:  # noqa: ANN001
    token = await make_user("rosa@example.com")
    document = sample_document(1)
    document["shapes"][0].update(kind="path", points=[[i % 7, i % 11] for i in range(2001)])
    body = await gql(CREATE, token, input={"name": "X", "material": "wood", "document": document})
    assert _code(body) == "TOO_MANY_POINTS"
    assert "2000" in body["errors"][0]["message"]


async def test_lists_show_mode_and_counts_of_the_current_version(gql: GraphQL, make_user) -> None:  # noqa: ANN001
    from tests.test_document import barniz_document

    token = await make_user("rosa@example.com")
    pattern_id = await _create(gql, token, shapes=4)
    listed = await gql("{ patterns { mode pieceCount layerCount } }", token)
    assert listed["data"]["patterns"] == [{"mode": "pattern", "pieceCount": 4, "layerCount": 0}]
    await gql(
        SAVE, token, input={"id": pattern_id, "baseVersion": 1, "document": barniz_document()}
    )
    one = await gql(
        "query($id: ID!) { pattern(id: $id) { mode pieceCount layerCount } }", token, id=pattern_id
    )
    assert one["data"]["pattern"] == {"mode": "barniz", "pieceCount": 2, "layerCount": 1}
