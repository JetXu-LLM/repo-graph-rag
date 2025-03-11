## Env setup
- `brew install graphviz inkscape`

### Generate knowledge graph json file
- `go run ts.go knowledge_graph.go <PROJECT_DIRECTORY>` - Generate knowledge_graph.json file

### Generate dot file from knowledge_graph.json
- `go run dot.go knowledge_graph.go` - Consume knowledge_graph.json and generate output.dot file

### Render dot file to svg
- `neato -Goverlap=false -Tpng output.dot -o vehicle.png` - Not recommended, neato has a bug to overlap the subgraphs
- `fdp -Tpng -Gdpi=300 output.dot -o vehicle.png` - Not recommended, it won't be able to render the large png
- `fdp -Tsvg output.dot -o vehicle.svg` - Recommended

### Open svg file using inkscape
- `inkscape vehicle.svg` - Chrome can open svg file as well. But sometimes svg files can be huge

### Generate topological graph for function calls
- `go run func_callgraph.go <PROJECT_DIRECTORY>`
