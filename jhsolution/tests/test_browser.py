from typing import Generator, Iterator, NoReturn
import contextlib, re, pytest, threading, time, uvicorn

from playwright.sync_api import Page, expect

from jhsolution.env import BROWSER_TEST_PORT
from jhsolution.main import app

#https://github.com/encode/uvicorn/issues/742#issuecomment-674411676
class ApplicationServer(uvicorn.Server):
	def install_signal_handlers(self) -> None: pass

	@contextlib.contextmanager
	def run_in_thread(self) -> Iterator[None]:
		thread = threading.Thread(target=self.run)
		thread.start()
		try:
			while not self.started:
				time.sleep(1e-3)
			yield
		finally:
			self.should_exit = True
			thread.join()

class TestBrowser:
	@pytest.fixture
	def host(self) -> str:
		return f"localhost:{BROWSER_TEST_PORT}"

	@pytest.fixture(autouse=True)
	def application(self) -> Generator[ApplicationServer, None, None]:
		assert BROWSER_TEST_PORT is not None
		config = uvicorn.Config(app, port=int(BROWSER_TEST_PORT))
		server = ApplicationServer(config)

		with server.run_in_thread():
			yield server

	@pytest.mark.dependency(
		scope="session", name="TestBrowserDummy", depends=["TestAPI"]
	)
	def test_start_dummy(self) -> None: pass

	@pytest.mark.dependency(
		scope="session", name="TestBrowser",
		depends=["test_rendering"]
	)
	def test_end_dummy(self) -> None: pass

	@pytest.mark.dependency(
		scope="session", name="test_rendering",
		depends=["TestBrowserDummy"]
	)
	def test_rendering(self, host: str, page: Page) -> None:
		page.goto(host)
		expect(page).to_have_title("JH솔루션")
