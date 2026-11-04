import ast
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from voice_cloning_claim_audit import phrases
from voice_cloning_claim_audit.audit import audit, claims, evidence, main, GENERIC

EXPECTED_POS = ('voice cloning', 'clones voice', 'clones a voice', 'clone a voice', 'clone voices', 'clones voices', 'voice clone', 'voice clones', 'cloned voice', 'cloned voices', 'speaker cloning', 'clones speaker voice', 'clone speaker voice', 'speaker voice cloning', 'voice cloning system', 'automatic voice cloning', 'zero shot voice cloning', 'clones your voice', 'clone your voice', 'clone any voice', 'clones any voice', 'clone a speaker voice', 'voice cloning technology', 'creates a voice clone', 'create a voice clone', 'generates speech in a cloned voice', 'synthesizes speech in a cloned voice', 'speech in a cloned voice', 'speaks in a cloned voice', 'speak in a cloned voice', 'cloned voice synthesis', 'cloned voice generation', 'voice clone generation', 'voice clone synthesis', 'replicates a voice', 'replicate a voice', 'replicates your voice', 'voice replication', 'replicates voices', 'mimic a voice', 'mimics a voice', 'mimics your voice', 'voice mimicry', 'imitates a voice', 'imitates your voice', 'voice imitation', 'clone the voice of', 'clones the voice of', 'voice cloning model', 'cloned speaker voice')
EXPECTED_NEG = ('no voice cloning', 'does not clone voice', 'does not clone voices', 'does not clone a voice', 'without voice cloning', 'no voice clone', 'does not create a voice clone', 'voice cloning not supported', 'does not clone your voice', 'no cloned voice', 'does not generate a cloned voice', 'does not synthesize a cloned voice', 'no speaker cloning', 'does not clone speaker voice', 'no voice cloning system', 'does not replicate a voice', 'does not mimic a voice', 'does not imitate a voice', 'no voice replication', 'no cloned voice synthesis', 'does not clone the voice of', 'without cloned voice', 'no voice clone generation', 'does not produce a cloned voice')

class AuditTests(unittest.TestCase):
    def fixture(self, text='voice cloning', files=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'README.md').write_text(text)
        for name, source in (files or {}).items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
        return root

    def cli(self, root, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main([str(root), *args])
        return code, out.getvalue()

    def test_phrase_oracle(self):
        # Parse source literals independently of imported constants.
        tree = ast.parse(Path(phrases.__file__).read_text())
        literals = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)}
        self.assertEqual(literals['VOICECLONE'], EXPECTED_POS)
        self.assertEqual(literals['NOVOICECLONE'], EXPECTED_NEG)
        self.assertEqual(len(EXPECTED_POS), 50)
        self.assertEqual(len(EXPECTED_NEG), 24)

    def test_all_phrases(self):
        for phrase in EXPECTED_POS:
            with self.subTest(phrase=phrase):
                self.assertTrue(claims(phrase)[0])
        for phrase in EXPECTED_NEG:
            with self.subTest(phrase=phrase):
                pos, neg = claims(phrase)
                self.assertFalse(pos)
                self.assertTrue(neg)

    def test_normalization_and_fences(self):
        self.assertEqual(claims("doesn't clone voice"), ([], ['does not clone voice']))
        self.assertTrue(claims('ZERO-shot  VOICE\ncloning')[0])
        self.assertFalse(claims('voice\n\ncloning')[0])
        self.assertFalse(claims('voic e cloning or voice cloningness')[0])
        for fence in ('```', '~~~', '   ````'):
            self.assertEqual(claims(fence+'\nvoice cloning\n'+fence), ([], []))
        self.assertTrue(claims('`voice cloning`')[0])

    def test_good_bad_and_denial(self):
        root = self.fixture(files={'app.py': 'api.clone_voice()'})
        self.assertEqual(self.cli(root)[0], 0)
        (root/'app.py').write_text('pass')
        code, output = self.cli(root, '--json')
        self.assertEqual(code, 2)
        result = json.loads(output)
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertEqual(result['findings'][0]['id'], 'documented-voice-cloning-claim-false')
        self.assertEqual(result['findings'][0]['severity'], 'HIGH')
        self.assertTrue(result['findings'][0]['message'])
        (root/'README.md').write_text('no voice cloning')
        (root/'app.py').write_text('api.clone_voice()')
        code, output = self.cli(root, '--json')
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)['findings'][0]['id'], 'documented-no-voice-cloning-claim-false')
        self.assertEqual(json.loads(output)['findings'][0]['severity'], 'HIGH')

    def test_test_only(self):
        for name in ('tests/app.py', 'test_app.py', 'app_test.py'):
            root = self.fixture(files={name: 'api.clone_voice()'})
            self.assertEqual(audit(root)['findings'][0]['severity'], 'MEDIUM')
            self.assertEqual(self.cli(root)[0], 0)
            self.assertEqual(self.cli(root, '--fail-on', 'MEDIUM')[0], 2)

    def test_no_source_and_no_claim(self):
        self.assertEqual(self.cli(self.fixture())[0], 2)
        self.assertEqual(self.cli(self.fixture('no voice cloning'))[0], 0)
        self.assertEqual(self.cli(self.fixture('Ordinary documentation'))[0], 0)

    def test_paths_and_ignore(self):
        for name in ('fixtures/a.py', 'docs/a.py', 'examples/a.py'):
            self.assertFalse(audit(self.fixture(files={name:'api.clone_voice()'}))['production_evidence'])
        root = self.fixture('Ordinary text', {'nested/docs/a.md':'voice cloning', 'src/a.py':'api.clone_voice()'})
        self.assertEqual(self.cli(root)[0], 0)
        self.assertEqual(self.cli(root, '--ignore', 'src')[0], 2)
        self.assertEqual(self.cli(root, '--ignore', 'src', '--ignore', 'nested')[0], 0)
        (root/'README.md').write_text('voice cloning')
        (root/'src/a.py').unlink()
        outside = self.fixture(files={'real.py':'api.clone_voice()'})
        (root/'link.py').symlink_to(outside/'real.py')
        (root/'linked').symlink_to(outside, target_is_directory=True)
        self.assertFalse(audit(root)['production_evidence'])

    def test_split_modules(self):
        for construct, call in [('VoiceCloner()', 'clone()'), ('TTS()', 'tts(speaker_wav=x)'), ('TextToSpeech()', 'tts(voice_samples=x)'), ('ToneColorConverter()', 'convert()')]:
            root = self.fixture(files={'a.py':'v='+construct, 'b.py':'v.'+call})
            self.assertEqual(self.cli(root)[0], 2)

    def test_usage_and_entry_points(self):
        for args in ([], ['--unknown'], ['/missing'], ['.', '--fail-on', 'BOGUS']):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                try:
                    code = main(args)
                except SystemExit as exc:
                    code = exc.code
            self.assertEqual(code, 1)
        result = subprocess.run([sys.executable, '-m', 'voice_cloning_claim_audit', '--version'], capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, '0.1.0'))
        config = Path(__file__).resolve().parents[1]/'pyproject.toml'
        if config.exists():
            self.assertIn('voice-cloning-claim-audit = "voice_cloning_claim_audit.audit:main"', config.read_text())

    def test_self_readme(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(claims((root/'README.md').read_text()), ([], []))
        self.assertEqual(audit(root)['verdict'], 'PASS')

    def test_positive_000(self):
        self.assertTrue(evidence('api.clone_voice()'))

    def test_positive_001(self):
        self.assertTrue(evidence('from library import clone_voice as run\nrun()'))

    def test_positive_002(self):
        self.assertTrue(evidence('api.clone_voices()'))

    def test_positive_003(self):
        self.assertTrue(evidence('from library import clone_voices as run\nrun()'))

    def test_positive_004(self):
        self.assertTrue(evidence('api.clone_speaker_voice()'))

    def test_positive_005(self):
        self.assertTrue(evidence('from library import clone_speaker_voice as run\nrun()'))

    def test_positive_006(self):
        self.assertTrue(evidence('api.clone_speaker()'))

    def test_positive_007(self):
        self.assertTrue(evidence('from library import clone_speaker as run\nrun()'))

    def test_positive_008(self):
        self.assertTrue(evidence('api.clone_any_voice()'))

    def test_positive_009(self):
        self.assertTrue(evidence('from library import clone_any_voice as run\nrun()'))

    def test_positive_010(self):
        self.assertTrue(evidence('api.clone_target_voice()'))

    def test_positive_011(self):
        self.assertTrue(evidence('from library import clone_target_voice as run\nrun()'))

    def test_positive_012(self):
        self.assertTrue(evidence('api.clone_reference_voice()'))

    def test_positive_013(self):
        self.assertTrue(evidence('from library import clone_reference_voice as run\nrun()'))

    def test_positive_014(self):
        self.assertTrue(evidence('api.clone_your_voice()'))

    def test_positive_015(self):
        self.assertTrue(evidence('from library import clone_your_voice as run\nrun()'))

    def test_positive_016(self):
        self.assertTrue(evidence('api.voice_clone()'))

    def test_positive_017(self):
        self.assertTrue(evidence('from library import voice_clone as run\nrun()'))

    def test_positive_018(self):
        self.assertTrue(evidence('api.voice_cloning()'))

    def test_positive_019(self):
        self.assertTrue(evidence('from library import voice_cloning as run\nrun()'))

    def test_positive_020(self):
        self.assertTrue(evidence('api.clone_voice_from_samples()'))

    def test_positive_021(self):
        self.assertTrue(evidence('from library import clone_voice_from_samples as run\nrun()'))

    def test_positive_022(self):
        self.assertTrue(evidence('api.clone_voice_from_audio()'))

    def test_positive_023(self):
        self.assertTrue(evidence('from library import clone_voice_from_audio as run\nrun()'))

    def test_positive_024(self):
        self.assertTrue(evidence('api.clone_voice_from_reference()'))

    def test_positive_025(self):
        self.assertTrue(evidence('from library import clone_voice_from_reference as run\nrun()'))

    def test_positive_026(self):
        self.assertTrue(evidence('api.synthesize_cloned_voice()'))

    def test_positive_027(self):
        self.assertTrue(evidence('from library import synthesize_cloned_voice as run\nrun()'))

    def test_positive_028(self):
        self.assertTrue(evidence('api.generate_cloned_voice()'))

    def test_positive_029(self):
        self.assertTrue(evidence('from library import generate_cloned_voice as run\nrun()'))

    def test_positive_030(self):
        self.assertTrue(evidence('api.create_voice_clone()'))

    def test_positive_031(self):
        self.assertTrue(evidence('from library import create_voice_clone as run\nrun()'))

    def test_positive_032(self):
        self.assertTrue(evidence('api.create_cloned_voice()'))

    def test_positive_033(self):
        self.assertTrue(evidence('from library import create_cloned_voice as run\nrun()'))

    def test_positive_034(self):
        self.assertTrue(evidence('api.build_voice_clone()'))

    def test_positive_035(self):
        self.assertTrue(evidence('from library import build_voice_clone as run\nrun()'))

    def test_positive_036(self):
        self.assertTrue(evidence('api.make_voice_clone()'))

    def test_positive_037(self):
        self.assertTrue(evidence('from library import make_voice_clone as run\nrun()'))

    def test_positive_038(self):
        self.assertTrue(evidence('api.synthesize_with_cloned_voice()'))

    def test_positive_039(self):
        self.assertTrue(evidence('from library import synthesize_with_cloned_voice as run\nrun()'))

    def test_positive_040(self):
        self.assertTrue(evidence('api.generate_with_cloned_voice()'))

    def test_positive_041(self):
        self.assertTrue(evidence('from library import generate_with_cloned_voice as run\nrun()'))

    def test_positive_042(self):
        self.assertTrue(evidence('api.speak_with_cloned_voice()'))

    def test_positive_043(self):
        self.assertTrue(evidence('from library import speak_with_cloned_voice as run\nrun()'))

    def test_positive_044(self):
        self.assertTrue(evidence('api.speak_in_cloned_voice()'))

    def test_positive_045(self):
        self.assertTrue(evidence('from library import speak_in_cloned_voice as run\nrun()'))

    def test_positive_046(self):
        self.assertTrue(evidence('api.synthesize_in_cloned_voice()'))

    def test_positive_047(self):
        self.assertTrue(evidence('from library import synthesize_in_cloned_voice as run\nrun()'))

    def test_positive_048(self):
        self.assertTrue(evidence('api.generate_speech_in_cloned_voice()'))

    def test_positive_049(self):
        self.assertTrue(evidence('from library import generate_speech_in_cloned_voice as run\nrun()'))

    def test_positive_050(self):
        self.assertTrue(evidence('api.clone_voice_with_samples()'))

    def test_positive_051(self):
        self.assertTrue(evidence('from library import clone_voice_with_samples as run\nrun()'))

    def test_positive_052(self):
        self.assertTrue(evidence('api.get_cloned_voice()'))

    def test_positive_053(self):
        self.assertTrue(evidence('from library import get_cloned_voice as run\nrun()'))

    def test_positive_054(self):
        self.assertTrue(evidence('api.get_voice_clone()'))

    def test_positive_055(self):
        self.assertTrue(evidence('from library import get_voice_clone as run\nrun()'))

    def test_positive_056(self):
        self.assertTrue(evidence('v=VoiceCloner()\nv.clone()'))

    def test_positive_057(self):
        self.assertTrue(evidence('lib.VoiceCloner().clone()'))

    def test_positive_058(self):
        self.assertTrue(evidence('from lib import VoiceCloner as C\nv=C()\nv.clone()'))

    def test_positive_059(self):
        self.assertTrue(evidence('VoiceCloner().clone()'))

    def test_positive_060(self):
        self.assertTrue(evidence('v=SpeakerCloner()\nv.synthesize()'))

    def test_positive_061(self):
        self.assertTrue(evidence('lib.SpeakerCloner().synthesize()'))

    def test_positive_062(self):
        self.assertTrue(evidence('from lib import SpeakerCloner as C\nv=C()\nv.synthesize()'))

    def test_positive_063(self):
        self.assertTrue(evidence('SpeakerCloner().synthesize()'))

    def test_positive_064(self):
        self.assertTrue(evidence('v=XTTSVoiceCloner()\nv.generate()'))

    def test_positive_065(self):
        self.assertTrue(evidence('lib.XTTSVoiceCloner().generate()'))

    def test_positive_066(self):
        self.assertTrue(evidence('from lib import XTTSVoiceCloner as C\nv=C()\nv.generate()'))

    def test_positive_067(self):
        self.assertTrue(evidence('XTTSVoiceCloner().generate()'))

    def test_positive_068(self):
        self.assertTrue(evidence('v=TTS()\nv.tts_to_file(speaker_wav=x)'))

    def test_positive_069(self):
        self.assertTrue(evidence('lib.TTS().tts_to_file(speaker_wav=x)'))

    def test_positive_070(self):
        self.assertTrue(evidence('from lib import TTS as C\nv=C()\nv.tts_to_file(speaker_wav=x)'))

    def test_positive_071(self):
        self.assertTrue(evidence('TTS().tts_to_file(speaker_wav=x)'))

    def test_positive_072(self):
        self.assertTrue(evidence('v=XTTS()\nv.tts(speaker_wav=x)'))

    def test_positive_073(self):
        self.assertTrue(evidence('lib.XTTS().tts(speaker_wav=x)'))

    def test_positive_074(self):
        self.assertTrue(evidence('from lib import XTTS as C\nv=C()\nv.tts(speaker_wav=x)'))

    def test_positive_075(self):
        self.assertTrue(evidence('XTTS().tts(speaker_wav=x)'))

    def test_positive_076(self):
        self.assertTrue(evidence('v=TextToSpeech()\nv.tts_with_preset(voice_samples=x)'))

    def test_positive_077(self):
        self.assertTrue(evidence('lib.TextToSpeech().tts_with_preset(voice_samples=x)'))

    def test_positive_078(self):
        self.assertTrue(evidence('from lib import TextToSpeech as C\nv=C()\nv.tts_with_preset(voice_samples=x)'))

    def test_positive_079(self):
        self.assertTrue(evidence('TextToSpeech().tts_with_preset(voice_samples=x)'))

    def test_positive_080(self):
        self.assertTrue(evidence('v=ToneColorConverter()\nv.convert()'))

    def test_positive_081(self):
        self.assertTrue(evidence('lib.ToneColorConverter().convert()'))

    def test_positive_082(self):
        self.assertTrue(evidence('from lib import ToneColorConverter as C\nv=C()\nv.convert()'))

    def test_positive_083(self):
        self.assertTrue(evidence('ToneColorConverter().convert()'))

    def test_positive_084(self):
        self.assertTrue(evidence('v=OpenVoiceToneColorConverter()\nv.convert()'))

    def test_positive_085(self):
        self.assertTrue(evidence('lib.OpenVoiceToneColorConverter().convert()'))

    def test_positive_086(self):
        self.assertTrue(evidence('from lib import OpenVoiceToneColorConverter as C\nv=C()\nv.convert()'))

    def test_positive_087(self):
        self.assertTrue(evidence('OpenVoiceToneColorConverter().convert()'))

    def test_positive_088(self):
        self.assertTrue(evidence('import lib.clone_voice as run\nrun()'))

    def test_positive_089(self):
        self.assertTrue(evidence('from lib import TTS\nx=TTS()\ndef tts(): pass\nx.tts(speaker_wav=y)'))

    def test_negative_000(self):
        self.assertFalse(evidence('import voice_cloning'))

    def test_negative_001(self):
        self.assertFalse(evidence('librosa.load(x)'))

    def test_negative_002(self):
        self.assertFalse(evidence('soundfile.read(x)'))

    def test_negative_003(self):
        self.assertFalse(evidence('wave.open(x).readframes(2)'))

    def test_negative_004(self):
        self.assertFalse(evidence('torchaudio.load(x)'))

    def test_negative_005(self):
        self.assertFalse(evidence('microphone.record()'))

    def test_negative_006(self):
        self.assertFalse(evidence('audio.play()'))

    def test_negative_007(self):
        self.assertFalse(evidence('engine.tts_to_file(text=x)'))

    def test_negative_008(self):
        self.assertFalse(evidence('gTTS(x).save(y)'))

    def test_negative_009(self):
        self.assertFalse(evidence('pyttsx3.init().say(x)'))

    def test_negative_010(self):
        self.assertFalse(evidence('engine.verify_speaker(x)'))

    def test_negative_011(self):
        self.assertFalse(evidence('engine.verify_files(x,y)'))

    def test_negative_012(self):
        self.assertFalse(evidence('engine.similarity(x,y)'))

    def test_negative_013(self):
        self.assertFalse(evidence('engine.diarize(x)'))

    def test_negative_014(self):
        self.assertFalse(evidence('engine.transcribe(x)'))

    def test_negative_015(self):
        self.assertFalse(evidence('engine.detect_voice_activity(x)'))

    def test_negative_016(self):
        self.assertFalse(evidence('engine.detect_keywords(x)'))

    def test_negative_017(self):
        self.assertFalse(evidence('engine.suppress_noise(x)'))

    def test_negative_018(self):
        self.assertFalse(evidence('engine.fingerprint(x)'))

    def test_negative_019(self):
        self.assertFalse(evidence('engine.detect_sound_events(x)'))

    def test_negative_020(self):
        self.assertFalse(evidence('engine.separate(x)'))

    def test_negative_021(self):
        self.assertFalse(evidence('engine.generate_audio(x)'))

    def test_negative_022(self):
        self.assertFalse(evidence('engine.generate_music(x)'))

    def test_negative_023(self):
        self.assertFalse(evidence('engine.recognize_emotion(x)'))

    def test_negative_024(self):
        self.assertFalse(evidence('engine.sentiment(x)'))

    def test_negative_025(self):
        self.assertFalse(evidence('engine.convert_voice(x)'))

    def test_negative_026(self):
        self.assertFalse(evidence('engine.voice_convert(x)'))

    def test_negative_027(self):
        self.assertFalse(evidence('engine.tts_with_vc_to_file(x)'))

    def test_negative_028(self):
        self.assertFalse(evidence('VoiceConverter().convert(x)'))

    def test_negative_029(self):
        self.assertFalse(evidence('engine.get_se(x)'))

    def test_negative_030(self):
        self.assertFalse(evidence('SpeakerEncoder().encode(x)'))

    def test_negative_031(self):
        self.assertFalse(evidence('engine.extract_speaker_embedding(x)'))

    def test_negative_032(self):
        self.assertFalse(evidence('load_reference_wav(x)'))

    def test_negative_033(self):
        self.assertFalse(evidence('tts.train(x)'))

    def test_negative_034(self):
        self.assertFalse(evidence('tts.fit(x)'))

    def test_negative_035(self):
        self.assertFalse(evidence('VoiceCloner()'))

    def test_negative_036(self):
        self.assertFalse(evidence('SpeakerCloner()'))

    def test_negative_037(self):
        self.assertFalse(evidence('other.clone()'))

    def test_negative_038(self):
        self.assertFalse(evidence('other.synthesize()'))

    def test_negative_039(self):
        self.assertFalse(evidence('other.generate()'))

    def test_negative_040(self):
        self.assertFalse(evidence('TTS()'))

    def test_negative_041(self):
        self.assertFalse(evidence('XTTS()'))

    def test_negative_042(self):
        self.assertFalse(evidence('v=TTS()\nv.tts_to_file(text=x)'))

    def test_negative_043(self):
        self.assertFalse(evidence('v=TTS()\nv.tts(x)'))

    def test_negative_044(self):
        self.assertFalse(evidence('other.tts(speaker_wav=x)'))

    def test_negative_045(self):
        self.assertFalse(evidence('TextToSpeech()'))

    def test_negative_046(self):
        self.assertFalse(evidence('v=TextToSpeech()\nv.tts_with_preset(x)'))

    def test_negative_047(self):
        self.assertFalse(evidence('other.tts(voice_samples=x)'))

    def test_negative_048(self):
        self.assertFalse(evidence('ToneColorConverter()'))

    def test_negative_049(self):
        self.assertFalse(evidence('other.convert()'))

    def test_negative_050(self):
        self.assertFalse(evidence('subprocess.run(["voice-clone"])'))

    def test_negative_051(self):
        self.assertFalse(evidence('"VoiceCloner().clone()"'))

    def test_negative_052(self):
        self.assertFalse(evidence('api.clone_voice'))

    def test_negative_053(self):
        self.assertFalse(evidence('clone_voice()'))

    def test_negative_054(self):
        self.assertFalse(evidence('def broken(:\n api.clone_voice()'))

    def test_negative_055(self):
        self.assertFalse(evidence('class VoiceCloner: pass\nv=VoiceCloner()\nv.clone()'))

    def test_negative_056(self):
        self.assertFalse(evidence('def VoiceCloner(): pass\nlib.VoiceCloner().clone()'))

    def test_negative_057(self):
        self.assertFalse(evidence('from lib import VoiceCloner as C\nclass C: pass\nC().clone()'))

    def test_negative_058(self):
        self.assertFalse(evidence('class SpeakerCloner: pass\nv=SpeakerCloner()\nv.synthesize()'))

    def test_negative_059(self):
        self.assertFalse(evidence('def SpeakerCloner(): pass\nlib.SpeakerCloner().synthesize()'))

    def test_negative_060(self):
        self.assertFalse(evidence('from lib import SpeakerCloner as C\nclass C: pass\nC().synthesize()'))

    def test_negative_061(self):
        self.assertFalse(evidence('class TTS: pass\nv=TTS()\nv.tts(speaker_wav=x)'))

    def test_negative_062(self):
        self.assertFalse(evidence('def TTS(): pass\nlib.TTS().tts(speaker_wav=x)'))

    def test_negative_063(self):
        self.assertFalse(evidence('from lib import TTS as C\nclass C: pass\nC().tts(speaker_wav=x)'))

    def test_negative_064(self):
        self.assertFalse(evidence('class XTTS: pass\nv=XTTS()\nv.tts(speaker_wav=x)'))

    def test_negative_065(self):
        self.assertFalse(evidence('def XTTS(): pass\nlib.XTTS().tts(speaker_wav=x)'))

    def test_negative_066(self):
        self.assertFalse(evidence('from lib import XTTS as C\nclass C: pass\nC().tts(speaker_wav=x)'))

    def test_negative_067(self):
        self.assertFalse(evidence('class TextToSpeech: pass\nv=TextToSpeech()\nv.tts(voice_samples=x)'))

    def test_negative_068(self):
        self.assertFalse(evidence('def TextToSpeech(): pass\nlib.TextToSpeech().tts(voice_samples=x)'))

    def test_negative_069(self):
        self.assertFalse(evidence('from lib import TextToSpeech as C\nclass C: pass\nC().tts(voice_samples=x)'))

    def test_negative_070(self):
        self.assertFalse(evidence('class ToneColorConverter: pass\nv=ToneColorConverter()\nv.convert()'))

    def test_negative_071(self):
        self.assertFalse(evidence('def ToneColorConverter(): pass\nlib.ToneColorConverter().convert()'))

    def test_negative_072(self):
        self.assertFalse(evidence('from lib import ToneColorConverter as C\nclass C: pass\nC().convert()'))

    def test_negative_073(self):
        self.assertFalse(evidence('def clone_voice(): pass\napi.clone_voice()'))

    def test_negative_074(self):
        self.assertFalse(evidence('from lib import clone_voice as run\ndef run(): pass\nrun()'))

    def test_negative_075(self):
        self.assertFalse(evidence('class Local:\n def clone_voice(self): pass\napi.clone_voice()'))


if __name__ == "__main__":
    unittest.main()
