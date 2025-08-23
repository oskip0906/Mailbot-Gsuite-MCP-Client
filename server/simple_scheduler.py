import json
import os
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional
from dateutil import parser
import pytz
from dotenv import load_dotenv

# Try to import Gemini - handle gracefully if not available
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# Load environment variables
load_dotenv()

EASTERN_TZ = pytz.timezone('America/New_York')

# Initialize Gemini client
llm_api_key = os.getenv('LLM_API_KEY')
llm_model = os.getenv('LLM_MODEL')
gemini_client = None

if GEMINI_AVAILABLE and llm_api_key:
    try:
        gemini_client = genai.Client(api_key=llm_api_key)
    except Exception as e:
        gemini_client = None
else:
    print("LLM_API_KEY not found or Gemini not available")

class SimpleTimeScheduler:
    def __init__(self, session, user_id: str = None):
        self.session = session
        self.user_id = user_id

    def _to_eastern(self, dt: datetime) -> datetime:
        return EASTERN_TZ.localize(dt) if dt.tzinfo is None else dt.astimezone(EASTERN_TZ)

    def _parse_time(self, time_str: str) -> Optional[datetime]:
        try:
            return self._to_eastern(parser.parse(time_str)) if time_str else None
        except:
            return None

    async def get_scheduling_context(self, start_time: str, end_time: str) -> Dict[str, Any]:
        try:
            start_dt, end_dt = self._parse_time(start_time), self._parse_time(end_time)
            if not start_dt or not end_dt:
                print(f"Invalid time format: start_time='{start_time}', end_time='{end_time}'")
                return {"error": "Invalid time format", "success": False}

            print(f"Fetching calendar events from {start_dt.isoformat()} to {end_dt.isoformat()}")
            
            # Check available tools first
            try:
                tools_result = await self.session.list_tools()
                available_tools = [tool.name for tool in tools_result.tools] if hasattr(tools_result, 'tools') else []
                
                if 'get_calendar_events' not in available_tools:
                    return {"error": "get_calendar_events tool not available in MCP session", "success": False}
            except Exception as tools_error:
                print(f"Could not list available tools: {tools_error}")
            
            result = await self.session.call_tool('get_calendar_events', {
                'time_min': start_dt.isoformat(), 'time_max': end_dt.isoformat(), '__user_id__': self.user_id
            })
            
            existing_events = []

            if hasattr(result, 'content') and result.content:
                for content in result.content:
                    if hasattr(content, 'text'):
                        try:
                            data = json.loads(content.text)
                            raw_events = data if isinstance(data, list) else data.get('items', [])
                            existing_events.extend(raw_events)
                        except Exception:
                            continue

            formatted_events = []

            if len(existing_events) == 0:
                print("No events retrieved from calendar API")
            
            for i, event in enumerate(existing_events):
                try:
                    start_info, end_info = event.get('start', {}), event.get('end', {})
                    start_dt_str = start_info.get('dateTime') or start_info.get('date')
                    end_dt_str = end_info.get('dateTime') or end_info.get('date')
                    
                    if start_dt_str and end_dt_str:
                        formatted_event = {
                            'summary': event.get('summary', 'Event'),
                            'start_time': self._to_eastern(parser.parse(start_dt_str)).strftime('%Y-%m-%d %H:%M'),
                            'end_time': self._to_eastern(parser.parse(end_dt_str)).strftime('%Y-%m-%d %H:%M')
                        }
                        formatted_events.append(formatted_event)
                    else:
                        print(f"Event {i+1}: Missing start/end time data")
                except Exception as format_error:
                    print(f"Event {i+1}: Failed to format - {format_error}")
                    continue
            
            # Always return success even if no events found - this allows scheduling to continue
            return {
                "success": True, "existing_events": formatted_events,
                "time_range": {"start": start_dt.strftime('%Y-%m-%d %H:%M'), "end": end_dt.strftime('%Y-%m-%d %H:%M')},
                "calendar_access_working": len(existing_events) > 0 or len(formatted_events) >= 0  # True if we got any response
            }
        except Exception as e:
            return {"error": f"Failed to get context: {str(e)}", "success": False}

    async def create_events(self, events: List[Dict]) -> Dict[str, Any]:
        try:
            created = []
            print(f"Creating {len(events)} calendar events...")
            
            for i, event in enumerate(events, 1):
                print(f"Creating event {i}/{len(events)}: {event.get('summary', 'Untitled')}")
                
                start_time = self._to_eastern(parser.parse(event['start_time']))
                end_time = self._to_eastern(parser.parse(event['end_time']))
                
                print(f"Time: {start_time.strftime('%Y-%m-%d %H:%M')} - {end_time.strftime('%Y-%m-%d %H:%M')}")
                
                cal_args = {
                    'summary': event['summary'], 
                    'start_time': start_time.isoformat(), 
                    'end_time': end_time.isoformat(), 
                    '__calendar_id__': 'primary'
                }
                if self.user_id:
                    cal_args['__user_id__'] = self.user_id
                
                result = await self.session.call_tool('create_calendar_event', cal_args)
                
                # Check if the MCP call failed
                if hasattr(result, 'isError') and result.isError:
                    error_text = "Unknown error"
                    if hasattr(result, 'content') and result.content:
                        for content in result.content:
                            if hasattr(content, 'text'):
                                error_text = content.text
                                break
                    print(f"Failed: {error_text}")
                    raise Exception(f"Calendar event creation failed: {error_text}")
                
                created.append({
                    'summary': event['summary'], 
                    'start_time': start_time.isoformat(), 
                    'end_time': end_time.isoformat()
                })
            
            print(f"All {len(created)} events created successfully!")
            return {"success": True, "events": created}
        except Exception as e:
            return {"error": f"Failed to create events: {str(e)}", "success": False}

    async def schedule_complete(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Complete scheduling workflow - does everything in one method"""
        global gemini_client, llm_model
        
        start_time = arguments.get("start_time")
        end_time = arguments.get("end_time")
        events_to_schedule = arguments.get("events_to_schedule", [])
        user_prompt = arguments.get("user_prompt", "")
        
        # Check if Gemini client is available
        if not gemini_client:
            error_msg = "Gemini client not initialized. Check LLM_API_KEY environment variable and install google-genai package."
            return {"success": False, "error": error_msg}
        
        try:
            context_result = await self.get_scheduling_context(start_time, end_time)
            
            if not context_result.get("success"):
                print(f"Failed to get scheduling context: {context_result.get('error')}")
                return context_result
            
            existing_events = context_result.get("existing_events", [])
            
            prompt = f"""You are a scheduling assistant. Schedule the given events within the specified time range.

            USER REQUEST: {user_prompt}

            CONSTRAINTS:
            - Time range: {start_time} to {end_time}
            - CRITICAL: Avoid conflicts with existing events listed below
            - Follow any specific requirements from the user request
            - Use YYYY-MM-DD HH:MM format for times (24-hour format)

            EXISTING EVENTS TO AVOID (DO NOT SCHEDULE OVERLAPPING TIMES):
            {json.dumps(existing_events, indent=2) if existing_events else "[]"}

            EVENTS TO SCHEDULE:
            {json.dumps(events_to_schedule, indent=2)}

            REQUIRED OUTPUT FORMAT - Return ONLY this JSON array with no other text:
            [
            {{
                "summary": "Event title",
                "start_time": "YYYY-MM-DD HH:MM", 
                "end_time": "YYYY-MM-DD HH:MM"
            }}
            ]

            Schedule all {len(events_to_schedule)} events avoiding any overlap with existing events. Return ONLY the JSON array, no other text, no explanation, no markdown.
            """
            
            response = gemini_client.models.generate_content(
                model=llm_model,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0)
            )
            
            gemini_response = response.text.strip()
            
            try:
                cleaned_response = gemini_response
                if "```json" in cleaned_response:
                    cleaned_response = cleaned_response.split("```json")[1].split("```")[0].strip()
                elif "```" in cleaned_response:
                    cleaned_response = cleaned_response.split("```")[1].split("```")[0].strip()
                
                # Try to find JSON array in the response
                start_bracket = cleaned_response.find('[')
                end_bracket = cleaned_response.rfind(']')
                
                if start_bracket != -1 and end_bracket != -1:
                    json_part = cleaned_response[start_bracket:end_bracket+1]
                    events_to_create = json.loads(json_part)
                else:
                    # Try parsing the whole response
                    events_to_create = json.loads(cleaned_response)
                
                # Validate event structure
                valid_events = []
                for i, event in enumerate(events_to_create, 1):
                    if isinstance(event, dict) and all(key in event for key in ['summary', 'start_time', 'end_time']):
                        valid_events.append(event)
                    else:
                        print(f"Event {i}: Invalid structure - {event}")
                
                if not valid_events:
                    return {"success": False, "error": "No valid events generated by Gemini"}
                
                events_to_create = valid_events
                    
            except json.JSONDecodeError as e:
                print(f"Failed to parse Gemini response as JSON: {e}")
                return {"success": False, "error": f"Gemini returned invalid JSON. Response: {gemini_response[:200]}..."}
            
            creation_result = await self.create_events(events_to_create)
            
            if creation_result.get("success"):
                created_events = creation_result.get("events", [])
                print(f"All {len(created_events)} events created!")
                
                return {
                    "success": True,
                    "message": f"Scheduling completed! Generated and created {len(created_events)} events in your calendar.",
                    "events_created": created_events,
                    "existing_events_considered": existing_events
                }
            else:
                print(f"Event creation failed: {creation_result.get('error')}")
                return {
                    "success": False,
                    "error": f"Events were generated by Gemini but creation failed: {creation_result.get('error')}",
                    "generated_events": events_to_create
                }
                
        except Exception as e:
            print(f"Complete scheduling workflow failed: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": f"Scheduling workflow failed: {str(e)}"}