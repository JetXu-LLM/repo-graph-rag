package analyzer

import (
	"fmt"
	"sort"
	"strings"
)

// Path represents a sequence of connected nodes
type Path []string

// Graph represents a directed graph using adjacency list
type Graph map[string][]string

// FindLongPaths finds all paths and sorted by path length
// Only returns paths with top 20% longest paths
func FindLongPaths(graph Graph) []Path {
	var allPaths []Path
	visited := make(map[string]bool)

	// Start DFS from each node
	for node := range graph {
		// We set minLength to 3 as we only want to find paths of at least 3 nodes
		dfs(graph, node, []string{}, visited, &allPaths, 3)
	}

	// Sort paths by length
	sort.Slice(allPaths, func(i, j int) bool {
		return len(allPaths[i]) > len(allPaths[j])
	})

	longestPathSize := len(allPaths)
	if longestPathSize > 25 {
		longestPathSize = longestPathSize / 5
	}
	if longestPathSize > 5000 { // Limit the number of paths to 5000
		longestPathSize = 5000
	}

	// Only return top 20% longest paths
	return allPaths[:longestPathSize]
}

// dfs performs depth-first search to find paths
func dfs(graph Graph, node string, currentPath []string, visited map[string]bool, allPaths *[]Path, minLength int) {
	// Mark current node as visited
	visited[node] = true

	// Add current node to path
	currentPath = append(currentPath, node)

	// If path has reached desired length, add it to results
	if len(currentPath) >= minLength {
		// Create a copy of the current path
		pathCopy := make([]string, len(currentPath))
		copy(pathCopy, currentPath)
		*allPaths = append(*allPaths, pathCopy)
	}

	// Explore neighbors
	for _, neighbor := range graph[node] {
		// Skip if neighbor is already in current path (avoid cycles)
		if !contains(currentPath, neighbor) {
			dfs(graph, neighbor, currentPath, visited, allPaths, minLength)
		}
	}

	// Backtrack: remove current node from path and mark as unvisited
	visited[node] = false
}

// contains checks if a slice contains a value
func contains(slice []string, value string) bool {
	for _, item := range slice {
		if item == value {
			return true
		}
	}
	return false
}

// KnowledgeGraphToGraph converts a StructuredKnowledgeGraph to a Graph representation
// that can be used with FindLongPaths
func KnowledgeGraphToGraph(skg *StructuredKnowledgeGraph) Graph {
	graph := make(Graph)

	// Add all nodes to the graph
	for _, node := range skg.Nodes {
		if node.Type == FunctionNode {
			graph[node.ID] = []string{}
		}
	}

	// Add edges to the graph
	for _, edge := range skg.Edges {
		if edge.RelationType == Calls {
			graph[edge.SourceID] = append(graph[edge.SourceID], edge.TargetID)
		}
	}

	return graph
}

type CommonPaths struct {
	CommonPath []string `json:"common_path"`
	Count      int      `json:"count"`
}

// CommonPathsCount finds common subpaths between paths of similar lengths
// and counts their frequency
func CommonPathsCount(paths []Path) []CommonPaths {
	// Map to store common paths and their counts
	commonPathMap := make(map[string]CommonPaths)

	fmt.Printf("Total paths: %d\nPaths length from: %d to %d\n", len(paths), len(paths[len(paths)-1]), len(paths[0]))

	// For each path, compare it only with paths of similar length
	for i, path := range paths {
		pathLen := len(path)

		// Compare with other paths of similar length (same, +1, or -1)
		for j, otherPath := range paths {
			otherPathLen := len(otherPath)

			// Skip comparing with itself
			if i <= j {
				break
			}
			if abs(pathLen-otherPathLen) > 1 {
				continue
			}

			fmt.Printf("Comparing path %d with path %d. Length: %d, %d\n", i, j, pathLen, otherPathLen)

			// Find the longest common subpath
			commonSubpath := findLongestCommonSubpath(path, otherPath)

			// Only consider common subpaths with at least 3 nodes
			if len(commonSubpath) >= 3 {
				// Convert commonSubpath to string key for map
				key := pathToString(commonSubpath)

				// Update count in map
				if entry, exists := commonPathMap[key]; exists {
					entry.Count++
					commonPathMap[key] = entry
				} else {
					commonPathMap[key] = CommonPaths{
						CommonPath: commonSubpath,
						Count:      1,
					}
				}
			}
		}
	}

	// Convert map to slice
	result := make([]CommonPaths, 0, len(commonPathMap))
	for _, cp := range commonPathMap {
		result = append(result, cp)
	}

	// Sort by count in descending order
	sort.Slice(result, func(i, j int) bool {
		return result[i].Count > result[j].Count
	})

	return result
}

// findLongestCommonSubpath finds the longest common subpath between two paths
func findLongestCommonSubpath(path1, path2 Path) Path {
	// Use dynamic programming to find the longest common subsequence
	m, n := len(path1), len(path2)
	dp := make([][]int, m+1)
	for i := range dp {
		dp[i] = make([]int, n+1)
	}

	// Fill the dp table
	for i := 1; i <= m; i++ {
		for j := 1; j <= n; j++ {
			if path1[i-1] == path2[j-1] {
				dp[i][j] = dp[i-1][j-1] + 1
			} else {
				dp[i][j] = max(dp[i-1][j], dp[i][j-1])
			}
		}
	}

	// Reconstruct the common subpath
	commonPath := make(Path, 0)
	i, j := m, n
	for i > 0 && j > 0 {
		if path1[i-1] == path2[j-1] {
			commonPath = append(Path{path1[i-1]}, commonPath...)
			i--
			j--
		} else if dp[i-1][j] > dp[i][j-1] {
			i--
		} else {
			j--
		}
	}

	return commonPath
}

// pathToString converts a path to a string for map key
func pathToString(path Path) string {
	return strings.Join(path, "->")
}

// max returns the maximum of two integers
func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

// abs returns the absolute value of an integer
func abs(x int) int {
	if x < 0 {
		return -x
	}
	return x
}
