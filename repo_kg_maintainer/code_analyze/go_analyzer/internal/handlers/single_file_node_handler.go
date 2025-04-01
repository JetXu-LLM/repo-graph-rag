package handlers

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

type NodeRequest struct {
	ProjectID   string `json:"projectID"`
	FileContent string `json:"fileContent"`
	FilePath    string `json:"filepath"`
}

func SingleFileNodeHandler(c *gin.Context) {
	var req NodeRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	if !strings.HasSuffix(req.FilePath, ".go") {
		c.JSON(http.StatusBadRequest, gin.H{"error": "File is not a Go file"})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "File processed successfully"})
}
