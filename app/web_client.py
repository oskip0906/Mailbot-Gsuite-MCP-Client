import json
import os
from typing import Dict, Any, Optional, List, Tuple
import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import types
from flask import Flask, render_template, request, jsonify
import datetime

class InteractiveMCPClient:
    def __init__(self, llm_api_key: str, llm_model: str, server_url: str, header_context: str, max_context_words: int):
        self.server_url = server_url
        self.available_tools = []
        self.llm_client = None
        self.llm_model_name = llm_model
        self.header_context = header_context.strip()
        self.conversation_history = ""
        self.interaction_count = 0
        self.max_context_words = max_context_words

        # Add date/time to the context
        current_datetime = datetime.datetime.now()
        current_date = current_datetime.strftime("%A, %B %d, %Y")
        timezone_name = current_datetime.astimezone().tzname()
        self.header_context += f"\nThe current date is: {current_date}. For timezone parameters, you MUST use the {timezone_name} timezone.\n"

        try:
            self.llm_client = genai.Client(api_key=llm_api_key)
        except ValueError as e:
            raise ValueError(f"Invalid LLM configuration: {e}")

    async def initialize(self) -> bool:
        """Initialize the client and load available tools"""
        try:
            await self._load_available_tools()
            return True
        except Exception as e:
            print(f"❌ An unexpected error occurred during initialization: {e}")
            return False

    async def _load_available_tools(self):
        """Load available tools from the server"""
        try:
            async with httpx.AsyncClient(base_url=self.server_url, timeout=30.0) as http_client:
                response = await http_client.get("/tools")
                response.raise_for_status()
                self.available_tools = response.json().get('tools', [])
        except Exception as e:
            print(f"⚠️ Failed to load tools from server: {e}")
            self.available_tools = []

    async def get_tool_and_arguments(self, user_request: str) -> Optional[Dict[str, Any]]:
        """Use LLM's native tool calling to determine which tool to use and extract arguments."""
        try:
            async with httpx.AsyncClient(base_url=self.server_url, timeout=30.0) as http_client:
                response = await http_client.get("/tools")
                response.raise_for_status()
                tools_info = response.json().get('tools', [])
        except Exception as e:
            print(f"⚠️ Could not fetch tools from server: {e}")
            return None
        
        # Convert tool specifications from the server into the format required by the Gemini API.
        function_declarations = []
        for tool_spec in tools_info:
            input_schema = tool_spec.get('input_schema')

            if input_schema and 'properties' in input_schema:
                properties = input_schema['properties']
                if 'user_id' in properties:
                    properties['__user_id__'] = properties.pop('user_id')

                required_params = [
                    param_name for param_name, param_props in input_schema['properties'].items()
                    if param_props.pop('required', False)
                ]
                if required_params:
                    input_schema['required'] = required_params

            function_declarations.append(
                types.FunctionDeclaration(
                    name=tool_spec['name'],
                    description=tool_spec['description'],
                    parameters=input_schema
                )
            )
        
        gemini_tools = [types.Tool(function_declarations=function_declarations)] if function_declarations else None

        if not gemini_tools:
            print("⚠️ No tools available to provide to the LLM.")
            return None

        try:
            # The user request is the main prompt. Context is provided for better understanding.
            llm_conversation = "Context: " + self.conversation_history + "\nInfo: " + self.header_context + "\nUser Request: " + user_request
            
            response = self.llm_client.models.generate_content(
                model=self.llm_model_name,
                contents=llm_conversation,
                config=types.GenerateContentConfig(
                    temperature=0,
                    tools=gemini_tools
                )
            )

            # Check the response for a tool call.
            if not response.candidates or not response.candidates[0].content.parts:
                return None

            part = response.candidates[0].content.parts[0]
            if not hasattr(part, 'function_call') or not part.function_call:
                return None

            function_call = part.function_call
            tool_name = function_call.name.strip()
            
            # Convert the arguments from a Struct to a dictionary.
            arguments = {key: value for key, value in function_call.args.items()}

            # Ensure user_id fields are correctly named.
            if 'user_id' in arguments:
                arguments['__user_id__'] = arguments.pop('user_id')

            available_tool_names = [t['name'] for t in tools_info]
            if tool_name not in available_tool_names:
                print(f"⚠️ LLM selected unknown tool: {tool_name}")
                return None

            return {'tool': tool_name, 'arguments': arguments}

        except Exception as e:
            print(f"⚠️ LLM API error or invalid response structure: {e}")
            return None


    async def handle_user_request(self, user_input: str):
        """Process a natural language user request"""
        user_input = user_input.strip()

        if user_input.lower() == 'list':
            return await self.list_available_tools()
        elif user_input.lower().startswith('inspect '):
            tool_name = user_input[8:].strip()
            return await self.inspect_specific_tool(tool_name)

        tool_result = await self.get_tool_and_arguments(user_input)
        
        response_data = {}
        final_response_text = ""

        if not tool_result:
            # If no tool was determined, use the LLM to provide a general response
            try:
                llm_conversation = "Context: " + self.conversation_history + "\nInfo: " + self.header_context + "\nUser Input: " + user_input
                response = self.llm_client.models.generate_content(
                    model=self.llm_model_name,
                    contents=llm_conversation
                )
                final_response_text = response.text.strip()
                response_data = {"response": final_response_text}
            except Exception as e:
                print(f"⚠️ LLM API error: {e}")
                final_response_text = f"LLM API error: {e}"
                response_data = {"error": final_response_text}
        else:
            detected_tool = tool_result['tool']
            arguments = tool_result['arguments']
            
            response_data = await self.execute_tool(detected_tool, arguments, user_input)

            if "response" in response_data:
                final_response_text = response_data["response"]
            elif "error" in response_data:
                final_response_text = response_data["error"]

        # Add the user input and the final model response to the history
        self.conversation_history += f"\nInteraction {self.interaction_count + 1}:"
        self.conversation_history += f"\nUser: {user_input}"
        if final_response_text:
            self.conversation_history += f"\nModel: {final_response_text}"
        self.interaction_count += 1
        # Check if context needs compression based on word count
        total_words = len(self.conversation_history.split())
        if total_words > self.max_context_words:
            print(f"📝 Context is getting long ({total_words} words). Compressing conversation history...")
            await self.compress_context()

        return response_data

    async def list_available_tools(self):
        """Fetch and display available tools from the server"""
        try:
            async with httpx.AsyncClient(base_url=self.server_url, timeout=30.0) as http_client:
                response = await http_client.get("/tools")
                response.raise_for_status()
                data = response.json()
                return data
        except Exception as e:
            return {"error": f"Failed to fetch tools: {e}"}

    async def inspect_specific_tool(self, tool_name: str):
        """Fetch and display details for a specific tool"""
        try:
            async with httpx.AsyncClient(base_url=self.server_url, timeout=30.0) as http_client:
                response = await http_client.get(f"/tools/{tool_name}")
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"error": f"Tool '{tool_name}' not found."}
            else:
                return {"error": f"Failed to inspect tool: {e}"}
        except Exception as e:
            return {"error": f"Failed to inspect tool: {e}"}

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any], user_input: str):
        """Execute a tool via the HTTP server"""
        try:
            async with httpx.AsyncClient(base_url=self.server_url, timeout=30.0) as http_client:
                request_body = {"tool_name": tool_name, "arguments": arguments}
                response = await http_client.post("/tools/call", json=request_body, timeout=30.0)
                response.raise_for_status()
                result = response.json()

            if result.get('success'):
                summary, raw_json = self.generate_response(tool_name, result.get('result'), user_input)
                return {"response": summary, "raw_json": raw_json, "tool_used": tool_name, "tool_input": arguments}
            else:
                return {"error": result.get('error', 'Unknown error'), "tool_used": tool_name, "tool_input": arguments}
        except Exception as e:
            return {"error": f"An error occurred while calling the tool: {e}", "tool_used": tool_name, "tool_input": arguments}

    def generate_response(self, tool_name: str, result: Any, user_input: str) -> Tuple[str, str]:
        """Format tool execution result using Gemini to provide a summary and return the raw JSON."""
        try:
            # Convert result to string for processing
            result_str = json.dumps(result, indent=2) if isinstance(result, (dict, list)) else str(result)
            
            # Use Gemini to summarize the result
            prompt = f"""
            Summarize the tool execution results in a clear, user-friendly way.
            If the result contains items with IDs (like email IDs or event IDs), you MUST include them in the summary as they are needed for follow-up actions like deleting or reading a specific item.
            Avoid showing raw JSON.
            
            CONVERSATION HISTORY:
            {self.conversation_history}
            
            TOOL EXECUTED: {tool_name}
            USER REQUEST: {user_input}
            RAW RESULT:
            {result_str}
            """
        
            response = self.llm_client.models.generate_content(
                model=self.llm_model_name,
                contents=prompt
            )

            summary = response.text.strip()
            return summary, result_str
            
        except Exception as e:
            # Fallback to simple formatting if Gemini fails
            print(f"⚠️ Could not generate LLM response: {e}")
            if isinstance(result, (dict, list)):
                result_str = json.dumps(result, indent=2)
                return result_str, result_str
            else:
                result_str = str(result)
                return result_str, result_str

    async def compress_context(self):
        """Compress conversation history by truncating the oldest parts."""
        print("Compressing conversation history by truncation...")
        words = self.conversation_history.split()
        
        if len(words) > self.max_context_words:
            # Keep the last `max_context_words` words
            words_to_keep = words[-self.max_context_words:]
            self.conversation_history = " ".join(words_to_keep)
            
            # Reset interaction count as the context has been shortened
            self.interaction_count = 0
            print(f"✅ Context compression successful. Kept last {self.max_context_words} words.")

app = Flask(__name__)

# Load environment variables
load_dotenv()
llm_key = os.getenv('LLM_API_KEY')
llm_model = os.getenv('LLM_MODEL')
server_url = os.getenv('MCP_SERVER_URL')

# Set header context and max context words
user_context="My name is Oscar Pang, I am an university student studying computer science."
system_context = "You are an AI assistant with deep expertise in Google Workspace. You can answer user questions about Gmail and Google Calendar, and you can execute actions by invoking the MCP tools."
header_context = f"{user_context}\n{system_context}"
max_context_words = 1000

# Initialize the client
try:
    client = InteractiveMCPClient(llm_key, llm_model, server_url, header_context, max_context_words)
except ValueError as e:
    print(f"❌ {e}")
    client = None

@app.before_request
async def initialize_client():
    if client and not client.available_tools:
        await client.initialize()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/command', methods=['POST'])
async def command():
    if not client:
        return jsonify({'error': 'Client not initialized'}), 500
    
    data = request.json
    user_input = data.get('input')
    
    if not user_input:
        return jsonify({'error': 'No input provided'}), 400

    response_data = await client.handle_user_request(user_input)
    
    return jsonify(response_data)

if __name__ == '__main__':
    app.run()
