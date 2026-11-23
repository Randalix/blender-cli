import sys, time, json
sys.path.insert(0, sys.argv[1])
t0=time.time()
from blmcp.tools_helpers import toolcode_format_call, toolcode_load_from_filepath, toolcode_wrap_with_calling_convention
from blmcp.tools_helpers.connection import send_code
import blmcp.tools.get_objects_summary as m
call = toolcode_wrap_with_calling_convention(toolcode_load_from_filepath(m.__file__))
r = send_code(toolcode_format_call(call, None), strict_json=True)
t1=time.time()
print("OBJ_SUMMARY", json.dumps(r)[:300]); print("ms", int((t1-t0)*1000))
t0=time.time()
r = send_code("import bpy\nbpy.ops.mesh.primitive_monkey_add()\nresult={'n':len(bpy.data.objects)}", strict_json=True)
print("EXEC", json.dumps(r)[:200], "ms", int((time.time()-t0)*1000))
