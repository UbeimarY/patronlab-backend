# GraphQL examples

Every operation below was run against the API built from this repository. Open GraphiQL at
`/graphql` (locally <http://localhost:8000/graphql>), sign in first, and add the header
`Authorization: Bearer <token>`. Replace `<PATTERN_ID>` with an id from `patterns`.

The document used in the variables is a small barniz plate: two layers, a radial group of
four petals and one `path` piece.

## 1. Sign in (paste the token in GraphiQL's headers as `{"Authorization": "Bearer <token>"}`)

```graphql
mutation { login(email: "artesana@demo.co", password: "…") { token expiresAt user { fullName } } }
```

## 2. My patterns, with mode and counts (no documents loaded)

```graphql
{ patterns { id name mode pieceCount layerCount currentVersion updatedAt } }
```

## 3. Create a barniz pattern

```graphql
mutation($doc: JSON!) {
  createPattern(input: { name: "Plato de prueba", material: "wood", document: $doc }) {
    id mode pieceCount layerCount currentVersion
  }
}
```

Variables:

```json
{"doc": {"schemaVersion": 2, "mode": "barniz", "width": 200, "height": 200, "background": "#f6efe3", "object": {"kind": "plate", "width": 200, "height": 200, "baseColor": "#1b1512", "leaf": "gold"}, "layers": [{"id": "l-1", "name": "Verde", "color": "#3f6b3a", "visible": true, "locked": false}, {"id": "l-2", "name": "Rojo", "color": "#b3202a", "visible": true, "locked": false}], "groups": [{"id": "g-1", "kind": "radial", "count": 4, "mirror": false, "sourceId": "p-1"}], "shapes": [{"id": "p-1", "kind": "leaf", "x": 100, "y": 60, "width": 20, "height": 44, "rotation": 0, "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-2", "groupId": "g-1"}, {"id": "p-2", "kind": "leaf", "x": 140, "y": 100, "width": 20, "height": 44, "rotation": 90, "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-2", "groupId": "g-1"}, {"id": "p-3", "kind": "leaf", "x": 100, "y": 140, "width": 20, "height": 44, "rotation": 180, "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-2", "groupId": "g-1"}, {"id": "p-4", "kind": "leaf", "x": 60, "y": 100, "width": 20, "height": 44, "rotation": 270, "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-2", "groupId": "g-1"}, {"id": "c-1", "kind": "path", "x": 100, "y": 100, "width": 0, "height": 0, "rotation": 0, "fill": "#3f6b3a", "stroke": "#2b2420", "layerId": "l-1", "groupId": null, "points": [[-18, -10], [18, -10], [22, 8], [0, 20], [-22, 8]]}]}}
```

## 4. One pattern: the document (always v2) and its versions

```graphql
query($id: ID!) {
  pattern(id: $id) { name mode document versions { number note shapeCount createdAt } }
}
```

Variables:

```json
{
  "id": "<PATTERN_ID>"
}
```

## 5. Duplicate a pattern

```graphql
mutation($id: ID!) { duplicatePattern(id: $id) { id name currentVersion } }
```

Variables:

```json
{
  "id": "<PATTERN_ID>"
}
```

## 6. Sketch to resin layers (a 64 px PNG: a red disc and a blue square)

```graphql
mutation($img: String!) {
  vectorizeImage(image: $img, width: 200, height: 200, colors: 3, detail: 0.6, minArea: 20) {
    layers { id name color areaShare } shapes elapsedMs notes
  }
}
```

Variables:

```json
{"img": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAA8UlEQVR42u2asRHCMAxFHZ0XoWYIFmCHLEDNPAzBKtSwiSlSwnHGkmwZnsrcSafnr1i2kqWUkmY2SZMbAAAAAMBYy0r/627/+vB4v3UDWNoa2du8h5B8DVCZejcM8c6+2ctYAZMkPKSQnkvoIcUf9AHbZTMXQfqLbhvzp0vIb/szjMxhLiyAa/s0jE8JAQAAAEEBvG+DVvGnV+DTjcy8l50OZ32Qx2WtVaDndISXeFoRJMJwihKaWQSp7zsaDKW7WQm1JeEqYG7LJs50OitPMsO/D+SA81q2UQAAAAAAAAAAAAAAAEiR/xdCAQAAAACAzZ6pDVJxu2sUBQAAAABJRU5ErkJggg=="}
```

## 7. Interactive evolution (send liked `variations[].document` back in `favorites`)

```graphql
mutation($doc: JSON!, $pal: [String!]!) {
  evolveVariations(document: $doc, palette: $pal, favorites: [],
                   weights: { balance: 0.2, overlap: 0.2, contrast: 0.5, coverage: 0.1 }, seed: 7) {
    original { total contrast }
    variations { score { total balance overlap contrast coverage } document }
    history { generation best average }
  }
}
```

Variables:

```json
{"doc": {"schemaVersion": 2, "mode": "barniz", "width": 200, "height": 200, "background": "#f6efe3", "object": {"kind": "plate", "width": 200, "height": 200, "baseColor": "#1b1512", "leaf": "gold"}, "layers": [{"id": "l-1", "name": "Verde", "color": "#3f6b3a", "visible": true, "locked": false}, {"id": "l-2", "name": "Rojo", "color": "#b3202a", "visible": true, "locked": false}], "groups": [{"id": "g-1", "kind": "radial", "count": 4, "mirror": false, "sourceId": "p-1"}], "shapes": [{"id": "p-1", "kind": "leaf", "x": 100, "y": 60, "width": 20, "height": 44, "rotation": 0, "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-2", "groupId": "g-1"}, {"id": "p-2", "kind": "leaf", "x": 140, "y": 100, "width": 20, "height": 44, "rotation": 90, "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-2", "groupId": "g-1"}, {"id": "p-3", "kind": "leaf", "x": 100, "y": 140, "width": 20, "height": 44, "rotation": 180, "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-2", "groupId": "g-1"}, {"id": "p-4", "kind": "leaf", "x": 60, "y": 100, "width": 20, "height": 44, "rotation": 270, "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-2", "groupId": "g-1"}, {"id": "c-1", "kind": "path", "x": 100, "y": 100, "width": 0, "height": 0, "rotation": 0, "fill": "#3f6b3a", "stroke": "#2b2420", "layerId": "l-1", "groupId": null, "points": [[-18, -10], [18, -10], [22, 8], [0, 20], [-22, 8]]}]}, "pal": ["#b3202a", "#1f5fa0", "#3f6b3a", "#f4c430"]}
```

## 8. Pareto front (NSGA-II)

```graphql
mutation($doc: JSON!, $pal: [String!]!) {
  paretoVariations(document: $doc, palette: $pal, seed: 0) {
    points { balance contrast materialSaving document } elapsedMs
  }
}
```

Variables:

```json
{"doc": {"schemaVersion": 2, "mode": "barniz", "width": 200, "height": 200, "background": "#f6efe3", "object": {"kind": "plate", "width": 200, "height": 200, "baseColor": "#1b1512", "leaf": "gold"}, "layers": [{"id": "l-1", "name": "Verde", "color": "#3f6b3a", "visible": true, "locked": false}, {"id": "l-2", "name": "Rojo", "color": "#b3202a", "visible": true, "locked": false}], "groups": [{"id": "g-1", "kind": "radial", "count": 4, "mirror": false, "sourceId": "p-1"}], "shapes": [{"id": "p-1", "kind": "leaf", "x": 100, "y": 60, "width": 20, "height": 44, "rotation": 0, "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-2", "groupId": "g-1"}, {"id": "p-2", "kind": "leaf", "x": 140, "y": 100, "width": 20, "height": 44, "rotation": 90, "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-2", "groupId": "g-1"}, {"id": "p-3", "kind": "leaf", "x": 100, "y": 140, "width": 20, "height": 44, "rotation": 180, "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-2", "groupId": "g-1"}, {"id": "p-4", "kind": "leaf", "x": 60, "y": 100, "width": 20, "height": 44, "rotation": 270, "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-2", "groupId": "g-1"}, {"id": "c-1", "kind": "path", "x": 100, "y": 100, "width": 0, "height": 0, "rotation": 0, "fill": "#3f6b3a", "stroke": "#2b2420", "layerId": "l-1", "groupId": null, "points": [[-18, -10], [18, -10], [22, 8], [0, 20], [-22, 8]]}]}, "pal": ["#b3202a", "#1f5fa0", "#3f6b3a", "#f4c430"]}
```

## 9. Nesting per layer on 120 × 120 mm sheets with RASTER

```graphql
mutation($doc: JSON!) {
  optimizeLayout(document: $doc, rollWidth: 300, spacing: 3, perLayer: true,
                 sheetWidth: 120, sheetHeight: 120, method: RASTER) {
    method usedLength wastePercent skylineWastePercent baselineWastePercent
    cutOrder cutTravel baselineCutTravel elapsedMs notes
    placements { shapeId x y width height angle }
    layers { layerId color areaCm2 sheets wastePercent placements { shapeId x y angle } }
  }
}
```

Variables:

```json
{"doc": {"schemaVersion": 2, "mode": "barniz", "width": 200, "height": 200, "background": "#f6efe3", "object": {"kind": "plate", "width": 200, "height": 200, "baseColor": "#1b1512", "leaf": "gold"}, "layers": [{"id": "l-1", "name": "Verde", "color": "#3f6b3a", "visible": true, "locked": false}, {"id": "l-2", "name": "Rojo", "color": "#b3202a", "visible": true, "locked": false}], "groups": [{"id": "g-1", "kind": "radial", "count": 4, "mirror": false, "sourceId": "p-1"}], "shapes": [{"id": "p-1", "kind": "leaf", "x": 100, "y": 60, "width": 20, "height": 44, "rotation": 0, "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-2", "groupId": "g-1"}, {"id": "p-2", "kind": "leaf", "x": 140, "y": 100, "width": 20, "height": 44, "rotation": 90, "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-2", "groupId": "g-1"}, {"id": "p-3", "kind": "leaf", "x": 100, "y": 140, "width": 20, "height": 44, "rotation": 180, "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-2", "groupId": "g-1"}, {"id": "p-4", "kind": "leaf", "x": 60, "y": 100, "width": 20, "height": 44, "rotation": 270, "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-2", "groupId": "g-1"}, {"id": "c-1", "kind": "path", "x": 100, "y": 100, "width": 0, "height": 0, "rotation": 0, "fill": "#3f6b3a", "stroke": "#2b2420", "layerId": "l-1", "groupId": null, "points": [[-18, -10], [18, -10], [22, 8], [0, 20], [-22, 8]]}]}}
```

## 10. Color check

```graphql
mutation($doc: JSON!) {
  analyzeColors(document: $doc) {
    pairs { a b deltaE tooSimilar } names { hex name } harmonies
  }
}
```

Variables:

```json
{"doc": {"schemaVersion": 2, "mode": "barniz", "width": 200, "height": 200, "background": "#f6efe3", "object": {"kind": "plate", "width": 200, "height": 200, "baseColor": "#1b1512", "leaf": "gold"}, "layers": [{"id": "l-1", "name": "Verde", "color": "#3f6b3a", "visible": true, "locked": false}, {"id": "l-2", "name": "Rojo", "color": "#b3202a", "visible": true, "locked": false}], "groups": [{"id": "g-1", "kind": "radial", "count": 4, "mirror": false, "sourceId": "p-1"}], "shapes": [{"id": "p-1", "kind": "leaf", "x": 100, "y": 60, "width": 20, "height": 44, "rotation": 0, "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-2", "groupId": "g-1"}, {"id": "p-2", "kind": "leaf", "x": 140, "y": 100, "width": 20, "height": 44, "rotation": 90, "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-2", "groupId": "g-1"}, {"id": "p-3", "kind": "leaf", "x": 100, "y": 140, "width": 20, "height": 44, "rotation": 180, "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-2", "groupId": "g-1"}, {"id": "p-4", "kind": "leaf", "x": 60, "y": 100, "width": 20, "height": 44, "rotation": 270, "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-2", "groupId": "g-1"}, {"id": "c-1", "kind": "path", "x": 100, "y": 100, "width": 0, "height": 0, "rotation": 0, "fill": "#3f6b3a", "stroke": "#2b2420", "layerId": "l-1", "groupId": null, "points": [[-18, -10], [18, -10], [22, 8], [0, 20], [-22, 8]]}]}}
```
