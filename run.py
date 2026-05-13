import subprocess
import sys

scripts = ["Gfeatch.py", "MD2HTML.py"]

for script in scripts:
    print(f"\n🚀 Running {script}...\n")
    
    result = subprocess.run(
        [sys.executable, script],
        text=True
    )
    
    if result.returncode != 0:
        print(f"❌ {script} failed. Stopping execution.")
        break
    else:
        print(f"✅ {script} completed successfully.")

print("\n🎉 All done.")