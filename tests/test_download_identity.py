"""Downloads from separate jobs must not share an osu! import directory."""
import io
from pathlib import Path
import zipfile
import pytest

from werkzeug.http import parse_options_header

from server import create_app
from studio.exporting import download_name, archive_osu_name, ensure_unique_archive


def job(id_, title='Song', artist='Artist'):
    return dict(id=id_,request=dict(keys=4,metadata=dict(title=title,artist=artist)))


def test_safe_stable_names_even_with_identical_metadata():
    first=job('a'*32,' ../CON:曲名<>"/\\|?*\r\n'+'長'*250,'A'*250)
    second=job('b'*32,**dict(title=first['request']['metadata']['title'],artist=first['request']['metadata']['artist']))
    one=download_name(first,'osz');two=download_name(second,'osz')
    assert one!=two and one==download_name(first,'osz')
    assert len(one)<110 and one.startswith('ManiaStudio ')
    assert all(c not in one for c in '<>:"/\\|?*\r\n')
    assert Path(download_name(first,'osu')).stem==Path(one).stem
    assert '曲名' in one and one.endswith('a'*32+'].osz')


def test_legacy_history_downloads_import_into_separate_folders(tmp_path):
    app=create_app(tmp_path/'workspace',run_worker=False)
    client=app.test_client();jobs=app.extensions['studio_jobs']
    # Existing history uses the original generic on-disk names and shared media
    # basenames. Repacking must preserve map/media bytes and need no generation.
    responses=[]
    for index in range(2):
        data=job(str(index+1)*32, title='同一首歌',artist='演出者')
        data.update(status='completed',stage='completed',created_at='2026-11-06T12:00:00Z',result={})
        jobs.items[data['id']]=data
        export=jobs.root/data['id']/'export';export.mkdir(parents=True)
        content=f'osu file format v14\n[General]\nAudioFilename: audio.mp3\n[HitObjects]\n64,192,{1000+index},1,0,0:0:0:0:\n'
        (export/'beatmap.osu').write_text(content,encoding='utf-8')
        (export/'result.json').write_text('{}')
        with zipfile.ZipFile(export/'beatmap.osz','w') as z:
            z.writestr('beatmap.osu',content)
            z.writestr('audio.mp3',f'audio-{index}')
        original=(export/'beatmap.osz').read_bytes()
        response=client.get(f"/api/jobs/{data['id']}/download/osz")
        assert response.status_code==200
        with zipfile.ZipFile(io.BytesIO(response.data)) as upgraded:
            assert upgraded.namelist()==[archive_osu_name(data['id']),'audio.mp3']
            assert upgraded.read(archive_osu_name(data['id']))==content.encode('utf-8')
            assert upgraded.read('audio.mp3')==f'audio-{index}'.encode()
        _,headers=parse_options_header(response.headers['Content-Disposition'])
        responses.append((headers['filename'],response.data))
        osu_response=client.get(f"/api/jobs/{data['id']}/download/osu")
        _,osu_headers=parse_options_header(osu_response.headers['Content-Disposition'])
        assert Path(osu_headers['filename']).stem==Path(headers['filename']).stem
        assert osu_response.data.decode('utf-8').replace('\r\n','\n')==content
        repeat=client.get(f"/api/jobs/{data['id']}/download/osz")
        assert repeat.headers['Content-Disposition']==response.headers['Content-Disposition']
        assert (export/'beatmap.osz').read_bytes()==response.data==repeat.data
        assert client.get(f"/api/jobs/{data['id']}/download/unknown").status_code==404
    assert responses[0][0]!=responses[1][0]
    # Reproduce stable's archive-basename extraction behavior without touching
    # the user's Songs directory or launching the game.
    songs=tmp_path/'Songs'
    for name,content in responses:
        folder=songs/Path(name).stem
        with zipfile.ZipFile(io.BytesIO(content)) as z:z.extractall(folder)
    assert len(list(songs.iterdir()))==2
    assert len({p.name for p in songs.glob('*/*.osu')})==2
    for i,(name,_) in enumerate(responses):
        assert (songs/Path(name).stem/'audio.mp3').read_text()==f'audio-{i}'


@pytest.mark.parametrize('permanent',[False,True])
def test_upgrade_is_atomic_when_windows_temporarily_locks_archive(tmp_path,monkeypatch,permanent):
    import studio.exporting as exporting
    archive=tmp_path/'beatmap.osz'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('beatmap.osu',b'unchanged map bytes')
        z.writestr('audio.mp3',b'unchanged audio bytes')
    before=archive.read_bytes();replace=exporting.os.replace;attempts=[]
    def locked(src,dst):
        attempts.append(1)
        if permanent or len(attempts)<3:raise PermissionError('locked')
        replace(src,dst)
    monkeypatch.setattr(exporting.os,'replace',locked)
    monkeypatch.setattr(exporting.time,'sleep',lambda _:None)
    if permanent:
        with pytest.raises(PermissionError):ensure_unique_archive(tmp_path,'a'*32)
        assert archive.read_bytes()==before
    else:
        ensure_unique_archive(tmp_path,'a'*32)
        assert len(attempts)==3
        with zipfile.ZipFile(archive) as z:
            assert z.read(archive_osu_name('a'*32))==b'unchanged map bytes'
            assert z.read('audio.mp3')==b'unchanged audio bytes'
    assert not list(tmp_path.glob('import-*.tmp'))
