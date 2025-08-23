import mcp
import json
from mcp.client.stdio import stdio_client
from simple_scheduler import SimpleTimeScheduler

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

async def schedule_events_complete(session, arguments, user_id=None):
    """Complete scheduling workflow - does everything in simple scheduler"""
    
    scheduler = SimpleTimeScheduler(session, user_id)
    result = await scheduler.schedule_complete(arguments)
    return result

# Available tools registry
CUSTOM_TOOLS = {
    "schedule_events_complete": {
        "function": schedule_events_complete,
        "schema": {
            "input": {
                "type": "object",
                "properties": {
                    "start_time": {"type": "string", "description": "Start time for scheduling window (e.g., '2024-01-15T09:00:00' or 'tomorrow')"},
                    "end_time": {"type": "string", "description": "End time for scheduling window (e.g., '2024-01-15T17:00:00' or 'end of week')"},
                    "events_to_schedule": {"type": "array", "description": "Events that need to be scheduled", "items": {"type": "object", "properties": {"summary": {"type": "string"}, "duration_minutes": {"type": "integer"}}}},
                    "user_prompt": {"type": "string", "description": "User's natural language scheduling request"},
                    "__user_id__": {"type": "string", "description": "The EMAIL of the Google account for which you are executing this action."}
                },
                "required": ["start_time", "end_time", "events_to_schedule", "__user_id__"]
            },
            "output": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "message": {"type": "string", "description": "Human-readable status message"},
                    "events_created": {"type": "array", "description": "Created calendar events"},
                    "error": {"type": "string"}
                },
                "required": ["success"]
            }
        },
        "description": "COMPLETE EVENT SCHEDULING: The ONLY tool needed for scheduling. Use this for ANY scheduling request (schedule events, plan week, create calendar entries, etc.). Does everything automatically: 1) Gets existing calendar events, 2) Generates optimal schedule avoiding conflicts using AI, 3) Creates all events in calendar. Just provide the time range, events to schedule, and user prompt."
    }
}

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
            print(f"🔧 Creating MCP session with server params:")
            print(f"   Command: {server_params.command}")
            print(f"   Args: {server_params.args}")
            
            # Create the client context
            self.client_context = stdio_client(server_params)
            self.read, self.write = await self.client_context.__aenter__()
            
            # Create the session context
            self.session = mcp.ClientSession(self.read, self.write)
            self.session_context = self.session
            await self.session_context.__aenter__()
            
            # Initialize the session
            await self.session.initialize()
            
            # List available tools for debugging
            try:
                tools_result = await self.session.list_tools()
                available_tools = [tool.name for tool in tools_result.tools] if hasattr(tools_result, 'tools') else []
                print(f"🔧 MCP session initialized with tools: {available_tools}")
            except Exception as tools_error:
                print(f"⚠️ Could not list tools after session init: {tools_error}")
            
            return self.session
        except Exception as e:
            await self.cleanup()
            print(f"❌ Failed to create session: {e}")
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
    """List all available tools including custom tools"""
    # List MCP tools
    result = await session.list_tools()
    print("Available MCP tools:")
    for tool in result.tools:
        print(f" • {tool.name}")
    
    # List custom tools
    print(f"\nAvailable custom tools:")
    for tool_name, tool_info in CUSTOM_TOOLS.items():
        print(f" • {tool_name} - {tool_info['description']}")
    
    total_tools = len(result.tools) + len(CUSTOM_TOOLS)
    print(f"\nFound {len(result.tools)} MCP tools and {len(CUSTOM_TOOLS)} custom tools ({total_tools} total).")
    return result

async def call_custom_tool(session, tool_name, arguments=None, user_id=None):
    """Call a custom tool with the provided arguments"""
    if arguments is None:
        arguments = {}
    
    if tool_name not in CUSTOM_TOOLS:
        print(f"Custom tool '{tool_name}' not found. Available custom tools: {list(CUSTOM_TOOLS.keys())}")
        return None
    
    try:
        tool_info = CUSTOM_TOOLS[tool_name]
        print(f"Calling custom tool: {tool_name}")
        print(f"Description: {tool_info['description']}")
        print(f"Arguments: {arguments}")
        
        # Call the tool function
        result = await tool_info['function'](session, arguments, user_id)
        
        print(f"\nCustom tool response:")
        print(result)
        
        return result
        
    except Exception as e:
        print(f"Error calling custom tool '{tool_name}': {e}")
        return None

async def inspect_custom_tool(tool_name):
    """Inspect a custom tool's schema without calling it"""
    if tool_name not in CUSTOM_TOOLS:
        print(f"Custom tool '{tool_name}' not found. Available custom tools: {list(CUSTOM_TOOLS.keys())}")
        return
    
    try:
        tool_info = CUSTOM_TOOLS[tool_name]
        print(f"\nCustom Tool: {tool_name}")
        print(f"Description: {tool_info['description']}")
        
        if 'schema' in tool_info and tool_info['schema']:
            schema = tool_info['schema']
            
            # Show input schema
            if 'input' in schema:
                input_schema = schema['input']
                print(f"\nInput Schema:")
                print(f"  Type: {input_schema.get('type', 'unknown')}")
                if 'properties' in input_schema:
                    print("  Properties:")
                    for prop_name, prop_info in input_schema['properties'].items():
                        required = prop_name in input_schema.get('required', [])
                        prop_type = prop_info.get('type', 'unknown')
                        description = prop_info.get('description', 'No description')
                        print(f"    • {prop_name} ({prop_type}){' [REQUIRED]' if required else ''}: {description}")
                        
                        # Show array item details
                        if prop_type == 'array' and 'items' in prop_info:
                            items_info = prop_info['items']
                            if 'properties' in items_info:
                                print(f"      Array items:")
                                for item_prop, item_details in items_info['properties'].items():
                                    item_required = item_prop in items_info.get('required', [])
                                    item_type = item_details.get('type', 'unknown')
                                    item_desc = item_details.get('description', 'No description')
                                    print(f"        - {item_prop} ({item_type}){' [REQUIRED]' if item_required else ''}: {item_desc}")
            
            # Show output schema
            if 'output' in schema:
                output_schema = schema['output']
                print(f"\nOutput Schema:")
                print(f"  Type: {output_schema.get('type', 'unknown')}")
                if 'properties' in output_schema:
                    print("  Properties:")
                    for prop_name, prop_info in output_schema['properties'].items():
                        required = prop_name in output_schema.get('required', [])
                        prop_type = prop_info.get('type', 'unknown')
                        description = prop_info.get('description', 'No description')
                        print(f"    • {prop_name} ({prop_type}){' [REQUIRED]' if required else ''}: {description}")
                        
                        # Show array item details
                        if prop_type == 'array' and 'items' in prop_info:
                            items_info = prop_info['items']
                            if 'properties' in items_info:
                                print(f"      Array items:")
                                for item_prop, item_details in items_info['properties'].items():
                                    item_required = item_prop in items_info.get('required', [])
                                    item_type = item_details.get('type', 'unknown')
                                    item_desc = item_details.get('description', 'No description')
                                    print(f"        - {item_prop} ({item_type}){' [REQUIRED]' if item_required else ''}: {item_desc}")
        else:
            print("No schema available.")
            
    except Exception as e:
        print(f"Error inspecting custom tool '{tool_name}': {e}")
