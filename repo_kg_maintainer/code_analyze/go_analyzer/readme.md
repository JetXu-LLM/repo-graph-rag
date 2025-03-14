Help me generate a go program to analyze golang project. Following requirements below:
1. Read the directory as a whole. Read go.mod file if possible.
2. Captures struct and interface definitions.
3. Stores each symbol in the analyzer's symbols map
4. Identifies regular functions and methods
5. The code entity includes: variables, functions, structs and interfaces.
6. variables can have a scope of global, parameter, local, function


type ImportInfo struct {
	Path  string // full import path
	Alias string // local name/alias (or last part of path if no alias)
}

type Module struct {
    ModulePath string
    ModuleDir  string
    Packages []Package
}

type Package struct {
    Name string
	Imports     map[string][]ImportInfo // key is the file path
    PackagePath string
    Files []string
    Structs []StructInfo
    Functions []Function
}

type StructInfo struct {
    MemberFunctions []Function
    Fields []StructField
}

type StructField struct {
	Name     string
	TypeName string
	TypePath string
}

## Useful Commands
- `go run ts.go knowledge_graph.go <PROJECT_DIRECTORY>` - Generate knowledge_graph.json file
- `go run dot.go knowledge_graph.go` - Consume knowledge_graph.json and generate output.dot file
- `neato -Goverlap=false -Tpng output.dot -o vehicle.png` - Not recommended, neato has a bug to overlap the subgraphs
- `fdp -Tpng -Gdpi=300 output.dot -o vehicle.png` - Not recommended, it won't be able to render the large png
- `fdp -Tsvg output.dot -o vehicle.svg`
- `inkscape vehicle.svg` - Run `brew install inkscape` if you don't have inkscape installed
