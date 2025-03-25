package analyzer

// Add a helper function to add edges to both graphs
func addEdge(
	kg *KnowledgeGraph,
	from *Node,
	to *Node,
	edgeType string,
	structuredKG *StructuredKnowledgeGraph,
) {
	// Add to original graph
	kg.Edges = append(kg.Edges, &Edge{
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
