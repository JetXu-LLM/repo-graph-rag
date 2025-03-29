package parser

import (
	"fmt"
	"os"

	sitter "github.com/smacker/go-tree-sitter"
	"github.com/tengteng/go-code-analyzer/internal/analyzer"
)

func ParseFile(
	filePath string,
	parser *sitter.Parser,
	debug bool,
	structuredKG *analyzer.StructuredKnowledgeGraph,
) error {
	content, err := os.ReadFile(filePath)
	if err != nil {
		return err
	}

	inputStr := string(content)
	tree := parser.Parse(nil, []byte(inputStr))
	if tree == nil {
		return fmt.Errorf("failed to parse file: %s", filePath)
	}
	defer tree.Close()

	// Use the new two-pass processing with debug flag
	ProcessASTNodes(tree.RootNode(), content, filePath, debug, structuredKG)

	return nil
}

// First, add a new function to process all nodes first
func ProcessASTNodes(
	root *sitter.Node,
	content []byte,
	filePath string,
	debug bool,
	structuredKG *analyzer.StructuredKnowledgeGraph,
) {
	if debug {
		fmt.Println("\nProcessing AST nodes for:", filePath)
	}

	// First pass: Process package declaration
	if debug {
		fmt.Println("- Processing package declaration")
	}
	analyzer.ProcessPackageDecl(root, content, filePath, structuredKG)

	// Second pass: Process all type declarations
	if debug {
		fmt.Println("- Processing type declarations")
	}
	analyzer.ProcessTypes(root, content, filePath, debug, structuredKG)

	// Third pass: Process everything else
	if debug {
		fmt.Println("- Processing other nodes")
	}
	analyzer.ProcessOtherNodes(root, content, filePath, debug, structuredKG)
}
