package analyzer

// Add a helper function to add edges to both graphs
func addEdge(
	from *Node,
	to *Node,
	edgeType string,
	structuredKG *StructuredKnowledgeGraph,
) {
	// Deduplicate edges
	if containsEdge(structuredKG.Kg.Edges, from, to, edgeType) {
		return
	}

	// Add to original graph
	structuredKG.Kg.Edges = append(structuredKG.Kg.Edges, &Edge{
		From: from,
		To:   to,
		Type: edgeType,
	})

	// Add to structured graph
	structuredEdge := GraphEdge{
		SourceType:   from.Type,
		SourceID:     generateNodeID(getNodeType(from.Type), from.Name, from.FilePath),
		TargetType:   to.Type,
		TargetID:     generateNodeID(getNodeType(to.Type), to.Name, to.FilePath),
		RelationType: EdgeType(edgeType),
	}
	structuredKG.Edges = append(structuredKG.Edges, structuredEdge)
}

func containsEdge(edges []*Edge, from *Node, to *Node, edgeType string) bool {
	for _, edge := range edges {
		if edge.From.Name == from.Name && edge.To.Name == to.Name && edge.Type == edgeType {
			return true
		}
	}
	return false
}
