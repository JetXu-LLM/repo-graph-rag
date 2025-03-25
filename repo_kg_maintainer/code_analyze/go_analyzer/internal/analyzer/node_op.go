package analyzer

import (
	"fmt"
	"path/filepath"
	"strings"

	mapset "github.com/deckarep/golang-set/v2"
	sitter "github.com/smacker/go-tree-sitter"
)

func getNodeType(nodeType string) NodeType {
	switch nodeType {
	case "package":
		return PackageNode
	case "type_spec":
		return StructNode
	case "function":
		return FunctionNode
	case "field":
		return FieldNode
	case "variable":
		return VariableNode
	case "enum":
		return EnumNode
	case "enum_value":
		return EnumValueNode
	case "import":
		return ImportNode
	default:
		return NodeType(nodeType)
	}
}

// addNode will update both the knowledge graph and the structured knowledge graph
func addNode(
	kg *KnowledgeGraph, nodeType, name, filePath string, startPos sitter.Point, endPos sitter.Point,
	parentStruct string, packageName string, structuredKG *StructuredKnowledgeGraph) *Node {
	var key string
	if nodeType == string(PackageNode) {
		filePath = filepath.Dir(filePath)
		key = fmt.Sprintf("%s:%s:%s", nodeType, name, filePath)
	} else {
		key = fmt.Sprintf("%s:%s:%s:%d", nodeType, name, filePath, startPos.Row+1)
	}
	if node, exists := kg.Nodes[key]; exists {
		return node
	}

	node := &Node{
		Type:         nodeType,
		Name:         name,
		FilePath:     filePath,
		Line:         startPos.Row + 1,
		Column:       startPos.Column + 1,
		EndLine:      endPos.Row + 1,
		EndColumn:    endPos.Column + 1,
		ParentStruct: parentStruct,
		PackageName:  packageName,
	}
	kg.Nodes[key] = node

	// Add to structured graph
	location := CodeLocation{
		FilePath: filePath,
		Line:     int(startPos.Row + 1),
		Col:      int(startPos.Column + 1),
		LineEnd:  int(endPos.Row + 1),
	}

	var structNodeType NodeType
	var nodeData interface{}
	var nodeID string

	switch nodeType {
	case "package":
		structNodeType = PackageNode
		nodeData = PackageInfo{
			PackageName: name,
			Location:    location,
		}
		nodeID = generateNodeID(structNodeType, name, filePath)
	case "import":
		structNodeType = ImportNode
		location.FilePath = ""
		nodeData = ImportInfo{
			ImportPath: name,
			Location:   location,
		}
		// We don't need the file path for import nodes ID
		nodeID = generateNodeID(structNodeType, name, "")
	case "type_spec":
		structNodeType = StructNode
		nodeData = StructInfo{
			PackageName: packageName,
			StructName:  name,
			Fields:      make([]string, 0),
			Location:    location,
		}
		nodeID = generateNodeID(structNodeType, name, filePath)
	case "function":
		structNodeType = FunctionNode
		nodeData = Function{
			PackageName:  packageName,
			FunctionName: name,
			InputParams:  "",
			ReturnParams: "",
			Location:     location,
		}
		nodeID = generateNodeID(structNodeType, name, filePath)
	case "field":
		parts := strings.SplitN(name, " ", 2)
		if len(parts) == 2 {
			// Generate parent struct ID if we have a parent struct
			var parentStructID string
			if parentStruct != "" {
				parentStructID = generateNodeID(StructNode, parentStruct, filePath)
			}

			structNodeType = FieldNode
			nodeData = FieldInfo{
				PackageName:  packageName,
				FieldName:    parts[0],
				FieldType:    parts[1],
				ParentStruct: parentStructID,
			}
			nodeID = generateNodeID(structNodeType, name, filePath)
		}
	case "variable":
		parts := strings.SplitN(name, " ", 2)
		if len(parts) == 2 {
			structNodeType = VariableNode
			nodeData = Variable{
				PackageName: packageName,
				VarName:     parts[0],
				VarType:     parts[1],
				Location:    location,
			}
			nodeID = generateNodeID(structNodeType, name, filePath)
		}
	}

	// Only add to structured graph if we have valid node data and it doesn't already exist
	if nodeData != nil {
		structuredNode := GraphNode{
			ID:   nodeID,
			Type: structNodeType,
			Data: nodeData,
		}
		structuredKG.Nodes = append(structuredKG.Nodes, structuredNode)
	}

	return node
}

func getNodeText(node *sitter.Node, content []byte) string {
	if node == nil {
		return ""
	}

	// Special handling for struct types
	if node.Type() == "struct_type" {
		return "struct"
	}

	// Special handling for slice types
	if node.Type() == "slice_type" {
		elementType := node.ChildByFieldName("element")
		if elementType != nil && elementType.Type() == "struct_type" {
			return "[]struct"
		}
	}

	// Special handling for maps with struct values
	if node.Type() == "map_type" {
		keyType := node.ChildByFieldName("key")
		valueType := node.ChildByFieldName("value")
		if valueType != nil && valueType.Type() == "struct_type" {
			return fmt.Sprintf("map[%s]struct", getNodeText(keyType, content))
		}
	}

	start := node.StartByte()
	end := node.EndByte()
	// Add a special treatment for `interface{}` because dot doesn't support `{}` well.
	ret := strings.ReplaceAll(string(content[start:end]), "interface{}", "interface")
	return strings.ReplaceAll(ret, "<-", "")
}

func isBuiltinType(typeName string) bool {
	builtinTypes := map[string]bool{
		"string":  true,
		"int":     true,
		"int8":    true,
		"int16":   true,
		"int32":   true,
		"int64":   true,
		"uint":    true,
		"uint8":   true,
		"uint16":  true,
		"uint32":  true,
		"uint64":  true,
		"float32": true,
		"float64": true,
		"bool":    true,
		"byte":    true,
		"rune":    true,
	}
	return builtinTypes[typeName]
}

func FindNodeID(nodeIds mapset.Set[string], filePath string, nodeName string) (string, bool) {
	sections := strings.Split(nodeName, ".")
	var nodeId string
	if len(sections) == 2 {
		// package.function
		funcName := sections[1]
		nodeId = fmt.Sprintf("function:%s:%s", funcName, filePath)
		if nodeIds.Contains(nodeId) {
			return nodeId, true
		}
	} else if len(sections) == 3 {
		// package.struct.function
		funcName := sections[2]
		structName := sections[1]
		nodeId = fmt.Sprintf("function:%s.%s:%s", structName, funcName, filePath)
		if nodeIds.Contains(nodeId) {
			return nodeId, true
		}
	}
	return "", false
}

// Update the generateNodeID function to accept NodeType
func generateNodeID(nodeType NodeType, name string, filePath string) string {
	if filePath == "" || nodeType == ImportNode {
		// For ImportNode id doesn't need filePath
		return fmt.Sprintf("%s:%s", string(nodeType), name)
	} else if nodeType == PackageNode {
		// Package node id doesn't need the filename
		return fmt.Sprintf("%s:%s:%s", string(nodeType), name, filepath.Dir(filePath))
	}
	return fmt.Sprintf("%s:%s:%s", string(nodeType), name, filePath)
}
