import unittest
import time
import threading
from app.worker import Worker

class TestWorker(unittest.TestCase):
    def setUp(self):
        self.worker = Worker(name="TestWorker", num_threads=2)

    def tearDown(self):
        self.worker.stop()
        # Ensure all threads are joined
        for t in self.worker._threads:
            t.join(timeout=1.0)

    def test_add_task_execution(self):
        """Test that a task executes and callback is called."""
        result_container = {}
        completed_event = threading.Event()

        def task_func(x, y):
            return x + y

        def on_complete(res):
            result_container['result'] = res
            completed_event.set()

        self.worker.add_task(task_func, 2, 3, on_complete=on_complete)
        
        # Wait for completion
        is_set = completed_event.wait(timeout=2.0)
        self.assertTrue(is_set, "Task did not complete in time")
        self.assertEqual(result_container.get('result'), 5)

    def test_worker_pause_resume(self):
        """Test pausing and resuming the worker."""
        # Pause immediately
        self.worker.pause()
        
        # Wait for threads to acknowledge pause (timeout is 0.5s in implementation)
        time.sleep(0.7)
        
        executed_event = threading.Event()
        
        def task_func():
            executed_event.set()
            return "done"

        self.worker.add_task(task_func)
        
        # Should not execute while paused
        is_set = executed_event.wait(timeout=0.5)
        self.assertFalse(is_set, "Task executed while paused")
        
        # Resume
        self.worker.resume()
        is_set = executed_event.wait(timeout=1.0)
        self.assertTrue(is_set, "Task did not execute after resume")

    def test_worker_stop(self):
        """Test stopping the worker clearing queue."""
        # Pause so tasks pile up
        self.worker.pause()
        
        mock_func = unittest.mock.Mock()
        self.worker.add_task(mock_func)
        self.worker.add_task(mock_func)
        
        # Stop and clear queue
        self.worker.stop(clear_queue=True)
        
        # Resume (should verify threads exit)
        self.assertFalse(self.worker._is_running)

if __name__ == '__main__':
    unittest.main()
