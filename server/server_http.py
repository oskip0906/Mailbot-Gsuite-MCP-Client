"""
FastAPI HTTP wrapper for MCP client
Exposes MCP functionality through REST API endpoints
"""
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from contextlib import asynccontextmanager
from server import create_session, list_tools, call_tool, inspect_tool, cleanup_session

# Global session manager
mcp_session = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage the MCP session lifecycle"""
    global mcp_session
    print("🔄 Starting MCP HTTP server...")
    try:
        mcp_session = await create_session()
        print("✅ MCP session initialized successfully!")
        yield
    except Exception as e:
        print(f"❌ Failed to initialize MCP session: {e}")
        raise
    finally:
        print("🔄 Shutting down MCP session...")
        await cleanup_session()
        print("✅ MCP session cleaned up!")

# Create FastAPI app with lifespan management
app = FastAPI(
    title="MCP HTTP API",
    description="HTTP wrapper for Model Context Protocol client",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware to allow web frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models for request/response schemas
class ToolCallRequest(BaseModel):
    tool_name: str
    arguments: Optional[Dict[str, Any]] = {}

class ToolCallResponse(BaseModel):
    success: bool
    tool_name: str
    arguments: Dict[str, Any]
    result: Optional[Any] = None
    error: Optional[str] = None

class ToolInfo(BaseModel):
    name: str
    description: str
    input_schema: Optional[Dict[str, Any]] = None

class ToolsListResponse(BaseModel):
    tools: List[ToolInfo]
    count: int

class HealthResponse(BaseModel):
    status: str
    mcp_session_active: bool
    
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    print("✅ Request received for health check endpoint '/health'")
    global mcp_session
    return HealthResponse(
        status="healthy" if mcp_session else "unhealthy",
        mcp_session_active=mcp_session is not None
    )

@app.get("/tools", response_model=ToolsListResponse)
async def get_tools_list():
    """List all available tools"""
    print("✅ Request received for tools list endpoint '/tools'")
    global mcp_session
    if not mcp_session:
        raise HTTPException(status_code=503, detail="MCP session not available")
    
    try:
        tools_result = await mcp_session.list_tools()
        tools_info = []
        for tool in tools_result.tools:
            tools_info.append(ToolInfo(
                name=tool.name,
                description=tool.description if hasattr(tool, 'description') else 'No description',
                input_schema=tool.inputSchema if hasattr(tool, 'inputSchema') else None
            ))
        return ToolsListResponse(tools=tools_info, count=len(tools_info))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list tools: {str(e)}")

@app.get("/tools/{tool_name}", response_model=ToolInfo)
async def inspect_mcp_tool(tool_name: str):
    """Get details for a specific tool"""
    print(f"✅ Request received for inspect tool endpoint '/tools/{tool_name}'")
    global mcp_session
    if not mcp_session:
        raise HTTPException(status_code=503, detail="MCP session not available")
    
    try:
        tools_result = await mcp_session.list_tools()
        for tool in tools_result.tools:
            if tool.name == tool_name:
                return ToolInfo(
                    name=tool.name,
                    description=tool.description if hasattr(tool, 'description') else 'No description',
                    input_schema=tool.inputSchema if hasattr(tool, 'inputSchema') else None
                )
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to inspect tool: {str(e)}")

@app.post("/tools/call", response_model=ToolCallResponse)
async def call_mcp_tool_generic(request: ToolCallRequest):
    """Generic endpoint to call any MCP tool"""
    global mcp_session
    if not mcp_session:
        raise HTTPException(status_code=503, detail="MCP session not available")
    
    try:
        result = await call_tool(mcp_session, request.tool_name, request.arguments)
        
        if result is None:
            return ToolCallResponse(
                success=False,
                tool_name=request.tool_name,
                arguments=request.arguments,
                error="Tool execution failed or tool not found"
            )
        
        # Extract the result content
        result_content = []
        for content in result.content:
            if hasattr(content, 'text'):
                result_content.append(content.text)
            else:
                result_content.append(str(content))
        
        return ToolCallResponse(
            success=True,
            tool_name=request.tool_name,
            arguments=request.arguments,
            result=result_content
        )
    
    except Exception as e:
        return ToolCallResponse(
            success=False,
            tool_name=request.tool_name,
            arguments=request.arguments,            
            error=str(e)
        )

if __name__ == "__main__":
    # Run the server
    uvicorn.run(
        "server_http:app",
        host="localhost",
        port=8080,
        log_level="info"
    )
