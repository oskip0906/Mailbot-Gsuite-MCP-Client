import asyncio, mcp
from mcp.client.stdio import stdio_client
from mcp.types import CallToolRequest

server_params = mcp.StdioServerParameters(
    command="uvx.exe",
    args=[
        "mcp-gsuite",
        "--gauth-file", ".gauth.json",
        "--accounts-file", ".accounts.json",
        "--credentials-dir", "credentials",
    ],
)

async def call_tool(session, tool_name, arguments=None):
    """Call a specific tool with the provided arguments"""
    if arguments is None:
        arguments = {}
    
    try:
        # Get the tool details first to validate it exists
        tools_result = await session.list_tools()
        tool_found = None
        for tool in tools_result.tools:
            if tool.name == tool_name:
                tool_found = tool
                break
        
        if not tool_found:
            print(f"Tool '{tool_name}' not found. Use 'list' to see available tools.")
            return None
        
        print(f"Calling tool: {tool_name}")
        print(f"Description: {tool_found.description}")
        print(f"Arguments: {arguments}")
        
        # Create the request with the provided arguments
        result = await session.call_tool(
            name=tool_name,
            arguments=arguments
        )
        print(f"\nTool response:")
        for content in result.content:
            if hasattr(content, 'text'):
                print(content.text)
            else:
                print(content)
        
        return result
                
    except Exception as e:
        print(f"Error calling tool '{tool_name}': {e}")
        return None

async def inspect_tool(session, tool_name):
    """Inspect a tool's schema without calling it"""
    try:
        tools_result = await session.list_tools()
        tool_found = None
        for tool in tools_result.tools:
            if tool.name == tool_name:
                tool_found = tool
                break
        
        if not tool_found:
            print(f"Tool '{tool_name}' not found.")
            return
        
        print(f"\nTool: {tool_name}")
        print(f"Description: {tool_found.description}")
        
        if hasattr(tool_found, 'inputSchema') and tool_found.inputSchema:
            print(f"\nInput Schema:")
            print(f"  Type: {tool_found.inputSchema.get('type', 'unknown')}")
            if 'properties' in tool_found.inputSchema:
                print("  Properties:")
                for prop_name, prop_info in tool_found.inputSchema['properties'].items():
                    required = prop_name in tool_found.inputSchema.get('required', [])
                    prop_type = prop_info.get('type', 'unknown')
                    description = prop_info.get('description', 'No description')
                    print(f"    • {prop_name} ({prop_type}){' [REQUIRED]' if required else ''}: {description}")
        else:
            print("No input schema available.")
            
    except Exception as e:
        print(f"Error inspecting tool '{tool_name}': {e}")

class MCPSessionManager:
    """Manages MCP session lifecycle"""
    def __init__(self):
        self.client_context = None
        self.session_context = None
        self.session = None
        self.read = None
        self.write = None

    async def create_session(self):
        """Create and initialize an MCP session"""
        try:
            # Create the client context
            self.client_context = stdio_client(server_params)
            self.read, self.write = await self.client_context.__aenter__()
            
            # Create the session context
            self.session = mcp.ClientSession(self.read, self.write)
            self.session_context = self.session
            await self.session_context.__aenter__()
            
            # Initialize the session
            await self.session.initialize()
            return self.session
        except Exception as e:
            await self.cleanup()
            print(f"Failed to create session: {e}")
            raise

    async def cleanup(self):
        """Clean up session resources"""
        try:
            if self.session_context:
                await self.session_context.__aexit__(None, None, None)
                self.session_context = None
                self.session = None
            
            if self.client_context:
                await self.client_context.__aexit__(None, None, None)
                self.client_context = None
                self.read = None
                self.write = None
        except Exception as e:
            print(f"Error during cleanup: {e}")

# Global session manager instance
_session_manager = None

async def create_session():
    """Create and initialize an MCP session"""
    global _session_manager
    _session_manager = MCPSessionManager()
    return await _session_manager.create_session()

async def cleanup_session():
    """Clean up the global session"""
    global _session_manager
    if _session_manager:
        await _session_manager.cleanup()
        _session_manager = None

async def list_tools(session):
    """List all available tools"""
    result = await session.list_tools()
    print("Available tools:")
    for tool in result.tools:
        print(f" • {tool.name}")
    print(f"\nFound {len(result.tools)} tools total.")
    return result
