"""Overlay tests are deliberately headless: never construct a native window."""
import ast
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from backend.config import Settings
from backend.overlay import AgentOverlay, aim, ENV_PORT
from backend.overlay_mascot import ROOT, asset_path, frame_index, load_frames, place_near, yellow_glow


def test_config(monkeypatch):
    monkeypatch.setenv('AGENT_OVERLAY', 'false')
    monkeypatch.setenv('AGENT_OVERLAY_MASCOT', 'false')
    monkeypatch.setenv('AGENT_OVERLAY_MASCOT_PATH', 'assets/custom')
    monkeypatch.setenv('AGENT_OVERLAY_MASCOT_SIZE', '180')
    cfg = Settings(_env_file=None)
    assert not cfg.agent_overlay and not cfg.agent_overlay_mascot
    assert cfg.agent_overlay_mascot_size == 180
    assert asset_path(cfg.agent_overlay_mascot_path) == ROOT / 'assets/custom'
    with pytest.raises(ValueError):
        Settings(_env_file=None, agent_overlay_mascot_size=900)


def test_master_off_never_starts_process(monkeypatch):
    monkeypatch.setattr('backend.overlay.subprocess.Popen', lambda *a, **k: pytest.fail('Spawned overlay'))
    overlay = AgentOverlay(False)
    assert overlay.start() is False
    overlay.close()


def test_mascot_options_and_close(monkeypatch):
    messages, killed = [], []
    proc = SimpleNamespace(poll=lambda: None, terminate=lambda: killed.append(True))
    def spawn(args, **kwargs):
        assert '--mascot-path' in args and '180' in args
        return proc
    monkeypatch.setattr('backend.overlay.subprocess.Popen', spawn)
    monkeypatch.setattr('backend.overlay.sys.platform', 'win32')
    monkeypatch.setattr('backend.overlay.send_to', lambda p, m: messages.append(m))
    overlay = AgentOverlay(mascot_size=180)
    assert overlay.start()
    overlay.close()
    assert messages[-1] == {'hide': True}
    assert killed and overlay.process is None and ENV_PORT not in __import__('os').environ
    assert AgentOverlay(mascot=False).options == []


def test_bounds_keep_existing_coordinates(monkeypatch):
    messages = []
    monkeypatch.setenv(ENV_PORT, '1234')
    monkeypatch.setattr('backend.overlay.send_to', lambda p,m: messages.append(m))
    assert aim(dict(x=10,y=20,width=100,height=40))
    assert messages == [{'at': [60,40], 'bounds': [10,20,100,40]}]
    assert not aim(None)


@pytest.mark.parametrize('bounds', [(500,400,100,40),(0,0,90,40),(1800,1000,120,80),(0,1000,90,80),(1800,0,120,40)])
def test_position_avoids_target_and_stays_on_screen(bounds):
    width,height=400,200
    x,y=place_near(bounds,(width,height),(0,0,1920,1080))
    bx,by,bw,bh=bounds
    assert 0 <= x <= 1920-width and 0 <= y <= 1080-height
    assert x+width <= bx or x >= bx+bw or y+height <= by or y >= by+bh


def test_negative_monitor_origin():
    x,y=place_near((-1900,10,100,40),(400,200),(-1920,0,1920,1080))
    assert -1920 <= x <= -400 and 0 <= y <= 880


def test_clock_does_not_restart_on_move():
    assert frame_index(1,10,8)==8
    assert frame_index(1.3,10,8)==0
    assert frame_index(1.4,10,8)==1


def test_small_slow_defaults_and_yellow_glow():
    cfg = Settings(_env_file=None)
    assert cfg.agent_overlay_mascot_size == 64
    assert cfg.agent_overlay_mascot_fps == 4
    width, height, frames = yellow_glow((1, 1, [bytes((10, 20, 30, 255))]), 3)
    assert (width, height) == (7, 7)
    assert frames[0][(3*7+3)*4:(3*7+4)*4] == bytes((10, 20, 30, 255))
    halo = frames[0][(2*7+3)*4:(2*7+4)*4]
    assert halo[2] > halo[1] > halo[0] and halo[3] > 0


def test_bad_asset_falls_back(tmp_path):
    assert load_frames(tmp_path,150) is None
    (tmp_path/'broken.png').write_bytes(b'broken')
    assert load_frames(tmp_path,150) is None


@pytest.mark.skipif(sys.platform!='win32',reason='Native Windows image decoder')
def test_real_frames_transparent_and_not_static():
    width,height,frames=load_frames('assets/melonman_working',150)
    assert (width,height,len(frames))==(150,150,10)
    assert len(set(frames))==10
    assert min(frames[0][3::4])==0
    assert max(frames[0][3::4])>240
    # Native compositor requires premultiplied BGRA, including transparent pixels.
    assert all(max(frame[i:i+3])<=frame[i+3] for frame in frames for i in range(0,len(frame),4))


@pytest.mark.skipif(sys.platform!='win32',reason='Win32 module')
def test_status_and_message_semantics(monkeypatch):
    from backend.overlay_window import Pointer, PALETTE
    assert set(PALETTE)=={'act','think','wait','done','stop'}
    pointer=Pointer.__new__(Pointer)
    pointer.text='Reading'; pointer.kind='act'; pointer.dirty=False
    pointer.mascot=(150,150,[b'']); pointer.visible=True
    pointer.target=[500,500]; pointer.cur=[100,100]; pointer.scale=1; pointer.expires=0
    pointer.animation_epoch=123
    pointer.mascot_position=lambda: (600,500)
    pointer.apply({'text':'Typing','kind':'wait'})
    assert pointer.target==[500,500] and pointer.cur==[100,100]
    assert pointer.kind=='wait' and pointer.animation_epoch==123
    pointer.apply({'at':[50,70], 'bounds':[20,60,60,20]})
    assert pointer.target==[600,500] and pointer.bounds==[20,60,60,20]
    pointer.apply({'hide':True})
    assert pointer.expires==0 and pointer.text==''


def test_completion_hides_overlay():
    # Lifecycle integration assertion without spawning a desktop/model agent.
    source=(ROOT/'backend/execution.py').read_text(encoding='utf-8')
    tree=ast.parse(source)
    finals=[node for node in ast.walk(tree) if isinstance(node,ast.Try) and node.finalbody]
    assert any('self.overlay.hide()' in ast.unparse(node.finalbody) for node in finals)
