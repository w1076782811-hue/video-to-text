#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""A/B 实验脚本：中文专用 paraformer（支持热词偏置）转写，用于与 SenseVoiceSmall 对比。

用法:
    python.exe transcribe_para.py [--timestamps] [--model <mid>] [--hotword "词1 词2"]
                                  [--no-punc] <音频路径>

与本技能主脚本 transcribe.py 的区别：
- 模型换成中文专用 paraformer（contextual / SeACo，支持 hotword），对准专业术语；
- 加 punc 模型补标点；
- stdout 同样只出纯稿（引擎提示走 stderr）。

注意：模型首次运行会从 ModelScope 下载到 config.json 指定的 models_cache_dir
（可用环境变量 VTT_MODELS_CACHE 覆盖）。
"""
import json
import sys
import os
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"
os.environ["OPENBLAS_NUM_THREADS"] = "2"

_cfg = {}
_cfgp = SKILL_DIR / "config.json"
if _cfgp.exists():
    try:
        _cfg = json.loads(_cfgp.read_text(encoding="utf-8"))
    except Exception:
        _cfg = {}

_MODEL_DIR = os.environ.get("VTT_MODELS_CACHE", _cfg.get("models_cache_dir", ""))
if _MODEL_DIR:
    os.environ["MODELSCOPE_CACHE"] = _MODEL_DIR
    os.environ["MODELSCOPE_LOCAL_CACHE"] = _MODEL_DIR
    os.environ["HF_HOME"] = _MODEL_DIR
    os.environ["HUGGINGFACE_HUB_CACHE"] = _MODEL_DIR

import subprocess
import tempfile

# 已实测：以下 ID 才是有效的（旧写法 speech_paraformer-large-contextual_asr_native_int_zh-cn
# 在 ModelScope 上是 404，会让 AutoModel 卡在下载重试里，表现为「加载模型」后长时间无输出）
DEFAULT_MODEL = "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
PUNC_MODEL = "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch"


def _mute_stdout():
    try:
        sys.stdout.flush()
        saved = os.dup(1)
        os.dup2(2, 1)
        return saved
    except Exception:
        return None


def _unmute_stdout(saved):
    if saved is None:
        return
    try:
        sys.stdout.flush()
        os.dup2(saved, 1)
        os.close(saved)
    except Exception:
        pass


def _find_ffmpeg():
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if os.path.exists(p):
            return p
    except Exception:
        pass
    env_ff = os.environ.get("VTT_FFMPEG")
    if env_ff and os.path.exists(env_ff):
        return env_ff
    bin_dir = _cfg.get("bin_dir") or os.environ.get("VTT_BIN_DIR", "")
    if bin_dir:
        name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        cand = os.path.join(bin_dir, name)
        if os.path.exists(cand):
            return cand
    return "ffmpeg"


FFMPEG = _find_ffmpeg()


def extract_audio(src, wav, ss=None, t=None):
    cmd = [FFMPEG, "-y"]
    if ss is not None:
        cmd += ["-ss", str(ss)]
    cmd += ["-i", src]
    if t is not None:
        cmd += ["-t", str(t)]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", wav]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _fmt_ms(ms):
    s = ms / 1000.0
    m = int(s // 60)
    return f"{m:02d}:{s - m * 60:05.2f}"


def main():
    args = sys.argv[1:]
    use_ts = "--timestamps" in args
    no_punc = "--no-punc" in args
    model_id = DEFAULT_MODEL
    hotword = ""
    ss = t = None
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--model":
            i += 1
            model_id = args[i]
        elif a == "--hotword":
            i += 1
            hotword = args[i]
        elif a in ("--timestamps", "--no-punc"):
            pass
        else:
            rest.append(a)
        i += 1
    if not rest:
        print("用法: transcribe_para.py [--timestamps] [--model id] [--hotword \"...\"] <音频>", file=sys.stderr)
        sys.exit(1)
    src = rest[0]
    if not os.path.exists(src):
        print(f"文件不存在: {src}", file=sys.stderr)
        sys.exit(1)

    wav = tempfile.mktemp(suffix=".wav")
    saved = _mute_stdout()
    result = None
    try:
        from funasr import AutoModel
        from funasr.utils.postprocess_utils import rich_transcription_postprocess
        print(f"[1/2] 抽音轨: {os.path.basename(src)}", file=sys.stderr)
        extract_audio(src, wav)
        kw = dict(model=model_id, vad_model="fsmn-vad",
                  vad_kwargs={"max_single_segment_time": 30000}, hub="ms", device="cpu")
        if not no_punc:
            kw["punc_model"] = PUNC_MODEL
        print(f"[2/2] 加载模型 {model_id} ...", file=sys.stderr)
        model = AutoModel(**kw)
        gen = dict(input=[wav], batch_size_s=300, merge_vad=True, merge_length_s=10,
                   sentence_timestamp=use_ts)
        if hotword:
            gen["hotword"] = hotword
            print(f"      热词({len(hotword.split())}个): {hotword[:120]}...", file=sys.stderr)
        res = model.generate(**gen)
        print("      推理完成", file=sys.stderr)
        if use_ts:
            result = []
            for si in res[0].get("sentence_info", []):
                result.append((si.get("start", 0), si.get("end", 0),
                               rich_transcription_postprocess(si["text"])))
        else:
            result = rich_transcription_postprocess(res[0]["text"])
    finally:
        _unmute_stdout(saved)
        if os.path.exists(wav):
            os.remove(wav)

    if use_ts:
        for a, b, txt in result:
            print(f"[{_fmt_ms(a)} - {_fmt_ms(b)}] {txt}")
    else:
        print(result)


if __name__ == "__main__":
    main()
