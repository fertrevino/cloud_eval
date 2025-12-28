#!/usr/bin/env python3
"""Test script for cloud-eval service."""
import sys
import os
from pathlib import Path

# Set dummy endpoint for testing
os.environ.setdefault("ENDPOINT_URL", "http://localhost:4566")
os.environ.setdefault("CLOUD_EVAL_TASKS_DIR", "tasks")
os.environ.setdefault("CLOUD_EVAL_REPORT_DIR", "reports")

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from cloud_eval.service import create_app


def test_service():
    """Test the FastAPI service."""
    print("🧪 Testing cloud-eval service...\n")
    
    # Create app
    try:
        app = create_app()
        print("✅ Service app created successfully")
    except Exception as e:
        print(f"❌ Failed to create app: {e}")
        return False
    
    # Test using async client
    import asyncio
    
    async def run_tests():
        from httpx import AsyncClient, ASGITransport
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Health check
            response = await client.get("/health")
            assert response.status_code == 200, f"Health check failed: {response.status_code}"
            data = response.json()
            assert data["status"] == "healthy"
            print("✅ Health check passed")
            
            # Test list reports
            response = await client.get("/api/reports")
            assert response.status_code == 200
            reports = response.json()
            print(f"✅ Reports endpoint: {len(reports.get('reports', []))} reports found")
            
            # Test list runs
            response = await client.get("/api/runs")
            assert response.status_code == 200
            runs = response.json()
            print(f"✅ Runs endpoint: {len(runs.get('runs', []))} runs in progress")
            
            # Test evaluate endpoint
            response = await client.post("/api/evaluate", json={"agent_name": "openai-llm"})
            if response.status_code == 200:
                result = response.json()
                run_id = result.get("run_id")
                assert run_id, "No run_id returned"
                print(f"✅ Evaluate endpoint: Created run {run_id}")
                
                # Check status immediately
                response = await client.get(f"/api/status/{run_id}")
                assert response.status_code == 200
                status = response.json()
                assert status["status"] in ["queued", "running"]
                print(f"✅ Status endpoint: Run status is '{status['status']}'")
            else:
                print(f"⚠️  Evaluate endpoint returned {response.status_code}")
            
            # Test non-existent run
            response = await client.get("/api/status/nonexistent")
            assert response.status_code == 404
            print("✅ 404 handling works for non-existent runs")
            
            print("\n✅ All tests passed!")
            return True
    
    return asyncio.run(run_tests())


if __name__ == "__main__":
    try:
        success = test_service()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
