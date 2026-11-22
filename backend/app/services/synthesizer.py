"""Phase 2 local GPU few-shot glyph synthesis using vendored FontDiffuser on GTX 1650."""

from __future__ import annotations

import gc
import threading
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.config import (
    ensure_data_dirs,
    get_content_font_candidates,
    get_fontdiffuser_ckpt_dir,
    get_glyphs_dir,
)
from app.db import get_conn, now_iso
from app.services.sheet_extractor import GLYPH_CANVAS_SIZE


class GlyphSynthesizer(ABC):
    """Abstract interface for local few-shot Chinese glyph synthesis."""

    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if local AI model weights and runtime are ready."""

    @abstractmethod
    def synthesize(self, char: str, style_ref_paths: list[Path], seed: int = 0) -> Optional[bytes]:
        """Return 256x256 RGBA PNG bytes for `char`, or None when unavailable."""


class NoopBlankSynthesizer(GlyphSynthesizer):
    """Fallback stub when AI weights/runtime are unavailable."""

    name = "noop_blank"

    def is_available(self) -> bool:
        return False

    def synthesize(self, char: str, style_ref_paths: list[Path], seed: int = 0) -> Optional[bytes]:
        return None


def _is_cjk(ch: str) -> bool:
    if not ch:
        return False
    cp = ord(ch[0])
    return (0x4E00 <= cp <= 0x9FFF) or (0x3400 <= cp <= 0x4DBF) or (0x20000 <= cp <= 0x2A6DF)


def _has_glyph(font: ImageFont.FreeTypeFont, char: str) -> bool:
    try:
        mask = font.getmask(char)
        if mask.getbbox() is None:
            return False
        notdef = font.getmask("\uffff")
        if bytes(mask) == bytes(notdef):
            return False
        return True
    except Exception:
        return False


def render_content_image(char: str, size: int = 96) -> Image.Image:
    """
    Render a centered black-on-white structure glyph image matching FontDiffuser's `ttf2im`.
    Checks KaiXinSongA -> KaiXinSongB -> Windows fallback fonts.
    """
    fsize = 128
    chosen_font: Optional[ImageFont.FreeTypeFont] = None
    for font_path in get_content_font_candidates():
        try:
            cand = ImageFont.truetype(font_path, 114)
            if _has_glyph(cand, char):
                chosen_font = cand
                break
        except Exception:
            continue

    if chosen_font is None:
        chosen_font = ImageFont.truetype(get_content_font_candidates()[0], 114)

    # Render onto oversized white canvas, crop tight ink bbox, center inside 128x128
    tmp = Image.new("L", (256, 256), 255)
    draw = ImageDraw.Draw(tmp)
    draw.text((128, 128), char, font=chosen_font, fill=0, anchor="mm")

    arr = np.asarray(tmp, dtype=np.uint8)
    ys, xs = np.where(arr < 245)
    canvas = Image.new("L", (fsize, fsize), 255)
    if ys.size > 0 and xs.size > 0:
        crop = tmp.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
        cw, ch_px = crop.size
        max_dim = int(fsize * 0.84)
        if cw > max_dim or ch_px > max_dim:
            scale = min(max_dim / cw, max_dim / ch_px)
            crop = crop.resize(
                (max(1, int(round(cw * scale))), max(1, int(round(ch_px * scale)))),
                Image.Resampling.BILINEAR,
            )
            cw, ch_px = crop.size
        paste_x = (fsize - cw) // 2
        paste_y = (fsize - ch_px) // 2
        canvas.paste(crop, (paste_x, paste_y))

    if size != fsize:
        canvas = canvas.resize((size, size), Image.Resampling.BILINEAR)
    return canvas.convert("RGB")


def glyph_png_to_style_96(image_path: Path, size: int = 96) -> Image.Image:
    """
    Convert a 256x256 transparent black-ink glyph PNG into a centered 96x96 white-bg RGB
    style reference image (~78% fill) so FontDiffuser's StyleEncoder sees crisp, properly framed strokes.
    """
    with Image.open(image_path) as img:
        rgba = img.convert("RGBA")
        alpha = np.asarray(rgba.split()[-1], dtype=np.float32) / 255.0

    ys, xs = np.where(alpha > 0.12)
    gray_full = np.clip((1.0 - alpha) * 255.0, 0, 255).astype(np.uint8)
    gray_pil = Image.fromarray(gray_full, mode="L")

    if ys.size == 0 or xs.size == 0:
        return gray_pil.resize((size, size), Image.Resampling.LANCZOS).convert("RGB")

    crop = gray_pil.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
    cw, ch_px = crop.size
    target_span = int(round(size * 0.78))
    scale = min(target_span / max(cw, 1), target_span / max(ch_px, 1))
    nw = max(1, int(round(cw * scale)))
    nh = max(1, int(round(ch_px * scale)))
    crop_resized = crop.resize((nw, nh), Image.Resampling.LANCZOS)

    out = Image.new("L", (size, size), 255)
    out.paste(crop_resized, ((size - nw) // 2, (size - nh) // 2))
    return out.convert("RGB")


def select_style_references(
    profile_id: str,
    style_glyph_ids: Optional[list[str]] = None,
    max_refs: int = 4,
) -> list[dict]:
    """
    Pick up to `max_refs` clean tablet glyphs for few-shot style conditioning.
    Prefers balanced CJK glyphs over extreme thin punctuation like '一' or '，'.
    """
    with get_conn() as conn:
        if style_glyph_ids:
            placeholders = ",".join("?" for _ in style_glyph_ids)
            rows = conn.execute(
                f"SELECT * FROM glyphs WHERE profile_id = ? AND id IN ({placeholders})",
                (profile_id, *style_glyph_ids),
            ).fetchall()
            valid = [dict(r) for r in rows if Path(r["image_path"]).exists()]
            if valid:
                return valid[:max_refs]

        rows = conn.execute(
            """
            SELECT * FROM glyphs
            WHERE profile_id = ? AND source = 'tablet'
            ORDER BY created_at DESC
            """,
            (profile_id,),
        ).fetchall()

    all_tablet = [dict(r) for r in rows if Path(r["image_path"]).exists()]
    if not all_tablet:
        return []

    cjk_balanced = [
        r
        for r in all_tablet
        if _is_cjk(r["char"])
        and 0.34 <= float(r["visual_width_ratio"]) <= 0.88
        and 0.34 <= float(r["visual_height_ratio"]) <= 0.88
    ]
    pool = cjk_balanced if cjk_balanced else all_tablet

    # Deduplicate by char and rank by closeness to balanced ~0.62 visual size
    seen_chars: set[str] = set()
    unique_pool: list[dict] = []
    for r in pool:
        if r["char"] not in seen_chars:
            seen_chars.add(r["char"])
            unique_pool.append(r)

    unique_pool.sort(
        key=lambda r: abs(float(r["visual_height_ratio"]) - 0.62)
        + abs(float(r["visual_width_ratio"]) - 0.60)
    )
    return unique_pool[:max_refs]


def get_target_height_ratio(profile_id: str) -> float:
    """Compute median visual_height_ratio of user's CJK tablet glyphs so AI glyphs match natural size."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT char, visual_height_ratio FROM glyphs WHERE profile_id = ? AND source = 'tablet'",
            (profile_id,),
        ).fetchall()
    ratios = [
        float(r["visual_height_ratio"])
        for r in rows
        if _is_cjk(r["char"]) and 0.30 <= float(r["visual_height_ratio"]) <= 0.90
    ]
    if not ratios:
        return 0.62
    return float(np.clip(np.median(ratios), 0.48, 0.76))


def postprocess_generated_glyph(
    pil_96: Image.Image,
    target_height_ratio: float = 0.62,
) -> dict:
    """
    Strip diffusion gray background noise, convert to crisp 256x256 anti-aliased RGBA,
    and rescale centered ink to match the user's natural tablet box proportion.
    """
    gray = np.asarray(pil_96.convert("L"), dtype=np.float32)
    bg = float(np.clip(np.percentile(gray, 92), 215.0, 255.0))
    denom = max(bg - 60.0, 75.0)
    alpha = np.clip((bg - 18.0 - gray) / denom, 0.0, 1.0)
    alpha[alpha < 0.08] = 0.0

    # Gentle S-curve contrast boost to sharpen diffusion stroke edges
    alpha = np.clip(np.power(alpha, 0.88) * 1.08, 0.0, 1.0)
    alpha_u8 = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)

    # Upscale 96 -> 256 smoothly + tiny unsharp polish
    up_alpha = Image.fromarray(alpha_u8, mode="L").resize(
        (GLYPH_CANVAS_SIZE, GLYPH_CANVAS_SIZE),
        Image.Resampling.LANCZOS,
    )
    up_alpha = up_alpha.filter(ImageFilter.UnsharpMask(radius=0.8, percent=45, threshold=4))

    up_arr = np.asarray(up_alpha, dtype=np.float32) / 255.0
    up_arr[up_arr < 0.06] = 0.0

    ys, xs = np.where(up_arr > 0.12)
    final_alpha = Image.new("L", (GLYPH_CANVAS_SIZE, GLYPH_CANVAS_SIZE), 0)

    if ys.size > 0 and xs.size > 0:
        x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
        raw_w = x1 - x0
        raw_h = y1 - y0
        raw_h_ratio = raw_h / GLYPH_CANVAS_SIZE

        # Match user's natural writing box scale when AI glyph is taller/shorter than typical tablet box
        scale_factor = target_height_ratio / max(raw_h_ratio, 0.25)
        scale_factor = float(np.clip(scale_factor, 0.58, 1.15))

        new_w = max(8, min(GLYPH_CANVAS_SIZE - 16, int(round(raw_w * scale_factor))))
        new_h = max(8, min(GLYPH_CANVAS_SIZE - 16, int(round(raw_h * scale_factor))))

        cropped = Image.fromarray(np.clip(up_arr[y0:y1, x0:x1] * 255.0, 0, 255).astype(np.uint8), mode="L")
        scaled = cropped.resize((new_w, new_h), Image.Resampling.LANCZOS)

        px = (GLYPH_CANVAS_SIZE - new_w) // 2
        py = (GLYPH_CANVAS_SIZE - new_h) // 2
        final_alpha.paste(scaled, (px, py))

    final_arr = np.asarray(final_alpha, dtype=np.float32) / 255.0
    fys, fxs = np.where(final_arr > 0.12)
    if fys.size == 0 or fxs.size == 0:
        bbox_x0, bbox_y0, bbox_x1, bbox_y1 = 0.20, 0.20, 0.80, 0.80
        ink_center_y = 0.50
    else:
        bbox_x0 = float(fxs.min()) / GLYPH_CANVAS_SIZE
        bbox_y0 = float(fys.min()) / GLYPH_CANVAS_SIZE
        bbox_x1 = float(fxs.max() + 1) / GLYPH_CANVAS_SIZE
        bbox_y1 = float(fys.max() + 1) / GLYPH_CANVAS_SIZE
        weights = final_arr[fys, fxs]
        ink_center_y = float(np.sum(fys * weights) / max(float(np.sum(weights)), 1e-6)) / GLYPH_CANVAS_SIZE

    rgba = Image.new("RGBA", (GLYPH_CANVAS_SIZE, GLYPH_CANVAS_SIZE), (0, 0, 0, 0))
    rgba.putalpha(final_alpha)

    return {
        "rgba_image": rgba,
        "bbox_x0": bbox_x0,
        "bbox_y0": bbox_y0,
        "bbox_x1": bbox_x1,
        "bbox_y1": bbox_y1,
        "visual_width_ratio": max(0.08, bbox_x1 - bbox_x0),
        "visual_height_ratio": max(0.08, bbox_y1 - bbox_y0),
        "ink_center_y": ink_center_y,
    }


def _dedup_chars(raw: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for ch in raw:
        if not ch.isspace() and ch not in seen:
            seen.add(ch)
            out.append(ch)
    return out


class FontDiffuserSynthesizer(GlyphSynthesizer):
    """Real local FontDiffuser few-shot synthesizer running on GTX 1650 CUDA (or CPU fallback)."""

    name = "fontdiffuser"
    REQUIRED_FILES = ("unet.pth", "style_encoder.pth", "content_encoder.pth")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pipe: Any = None
        self._model: Any = None
        self._args: Any = None
        self._device: str = "cpu"
        self._extra_style_refs: Any = None
        self._cached_feats: Optional[dict[str, Any]] = None

    def get_status(self) -> dict:
        ckpt_dir = get_fontdiffuser_ckpt_dir()
        missing = [
            f
            for f in self.REQUIRED_FILES
            if not (ckpt_dir / f).exists() or (ckpt_dir / f).stat().st_size < 1_000_000
        ]
        ckpt_ready = len(missing) == 0

        cuda_available = False
        gpu_name = None
        vram_total_mb = 0
        vram_allocated_mb = 0
        error: Optional[str] = None

        try:
            import torch

            cuda_available = bool(torch.cuda.is_available())
            if cuda_available:
                props = torch.cuda.get_device_properties(0)
                gpu_name = props.name
                vram_total_mb = int(round(props.total_memory / (1024 * 1024)))
                vram_allocated_mb = int(round(torch.cuda.memory_allocated(0) / (1024 * 1024)))
        except Exception as exc:
            error = f"PyTorch 不可用: {exc}"

        if not ckpt_ready and error is None:
            error = f"缺少模型权重文件: {', '.join(missing)}"

        return {
            "available": ckpt_ready and error is None,
            "cuda_available": cuda_available,
            "device": "cuda" if cuda_available else "cpu",
            "gpu_name": gpu_name,
            "vram_total_mb": vram_total_mb,
            "vram_allocated_mb": vram_allocated_mb,
            "ckpt_ready": ckpt_ready,
            "ckpt_dir": str(ckpt_dir),
            "loaded": self._pipe is not None,
            "missing_files": missing,
            "error": error,
        }

    def is_available(self) -> bool:
        return bool(self.get_status()["available"])

    def _build_args(self, guidance_scale: float = 7.5, num_inference_steps: int = 20):
        import sys

        backend_dir = str(Path(__file__).resolve().parents[2])
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)

        from third_party.fontdiffuser.configs.fontdiffuser import get_parser

        parser = get_parser()
        args = parser.parse_args([])
        args.resolution = 96
        args.style_image_size = (96, 96)
        args.content_image_size = (96, 96)
        args.content_encoder_downsample_size = 3
        args.channel_attn = True
        args.content_start_channel = 64
        args.style_start_channel = 64
        args.model_type = "noise"
        args.guidance_type = "classifier-free"
        args.guidance_scale = guidance_scale
        args.num_inference_steps = num_inference_steps
        args.order = 2
        args.algorithm_type = "dpmsolver++"
        args.skip_type = "time_uniform"
        args.method = "multistep"
        args.correcting_x0_fn = None
        args.t_start = None
        args.t_end = None
        return args

    def ensure_loaded(self) -> None:
        with self._lock:
            if self._pipe is not None:
                return

            import sys
            import torch

            backend_dir = str(Path(__file__).resolve().parents[2])
            if backend_dir not in sys.path:
                sys.path.insert(0, backend_dir)

            from third_party.fontdiffuser.src import (
                FontDiffuserDPMPipeline,
                FontDiffuserModelDPM,
                build_content_encoder,
                build_ddpm_scheduler,
                build_style_encoder,
                build_unet,
            )

            ckpt_dir = get_fontdiffuser_ckpt_dir()
            for fname in self.REQUIRED_FILES:
                p = ckpt_dir / fname
                if not p.exists() or p.stat().st_size < 1_000_000:
                    raise FileNotFoundError(f"FontDiffuser 权重文件不存在或不完整: {p}")

            args = self._build_args()
            device = "cuda" if torch.cuda.is_available() else "cpu"

            def _load_sd(path: Path):
                try:
                    return torch.load(str(path), map_location="cpu", weights_only=True)
                except Exception:
                    return torch.load(str(path), map_location="cpu", weights_only=False)

            unet = build_unet(args=args)
            unet.load_state_dict(_load_sd(ckpt_dir / "unet.pth"))
            style_encoder = build_style_encoder(args=args)
            style_encoder.load_state_dict(_load_sd(ckpt_dir / "style_encoder.pth"))
            content_encoder = build_content_encoder(args=args)
            content_encoder.load_state_dict(_load_sd(ckpt_dir / "content_encoder.pth"))

            synth_ref = self

            class CachedMultiRefModelDPM(FontDiffuserModelDPM):
                """Caches content/style encodings across DPM steps and averages few-shot style features."""

                def forward(self, x_t, timesteps, cond, content_encoder_downsample_size, version):
                    content_images = cond[0]
                    style_images = cond[1]
                    bs = content_images.shape[0]

                    style_enc = self._modules["style_encoder"]
                    content_enc = self._modules["content_encoder"]
                    unet_mod = self._modules["unet"]

                    cache = synth_ref._cached_feats
                    if cache is not None and cache["bs"] == bs:
                        style_img_feature = cache["style_img_feature"]
                        style_hidden_states = cache["style_hidden_states"]
                        content_residual_features = list(cache["content_residual_features"])
                        style_content_res_features = list(cache["style_content_res_features"])
                    else:
                        if synth_ref._extra_style_refs is not None and bs == 2:
                            # Batch 0 = uncond (all ones), Batch 1 = few-shot averaged style refs
                            uncond_feat, _, _ = style_enc(style_images[0:1])
                            ref_feats, _, _ = style_enc(synth_ref._extra_style_refs)
                            avg_cond_feat = ref_feats.mean(dim=0, keepdim=True)
                            style_img_feature = torch.cat([uncond_feat, avg_cond_feat], dim=0)
                        elif synth_ref._extra_style_refs is not None and bs == 1:
                            ref_feats, _, _ = style_enc(synth_ref._extra_style_refs)
                            style_img_feature = ref_feats.mean(dim=0, keepdim=True)
                        else:
                            style_img_feature, _, _ = style_enc(style_images)

                        b, ch_dim, h, w = style_img_feature.shape
                        style_hidden_states = style_img_feature.permute(0, 2, 3, 1).reshape(b, h * w, ch_dim)

                        c_feat, content_residual_features = content_enc(content_images)
                        content_residual_features.append(c_feat)

                        sc_feat, style_content_res_features = content_enc(style_images)
                        style_content_res_features.append(sc_feat)

                        synth_ref._cached_feats = {
                            "bs": bs,
                            "style_img_feature": style_img_feature,
                            "style_hidden_states": style_hidden_states,
                            "content_residual_features": tuple(content_residual_features),
                            "style_content_res_features": tuple(style_content_res_features),
                        }

                    input_hidden_states = [
                        style_img_feature,
                        content_residual_features,
                        style_hidden_states,
                        style_content_res_features,
                    ]
                    out = unet_mod(
                        x_t,
                        timesteps,
                        encoder_hidden_states=input_hidden_states,
                        content_encoder_downsample_size=content_encoder_downsample_size,
                    )
                    return out[0]

            model = CachedMultiRefModelDPM(
                unet=unet,
                style_encoder=style_encoder,
                content_encoder=content_encoder,
            )
            model.eval()
            model.to(device=device, dtype=torch.float32)

            train_scheduler = build_ddpm_scheduler(args=args)
            pipe = FontDiffuserDPMPipeline(
                model=model,
                ddpm_train_scheduler=train_scheduler,
                model_type=args.model_type,
                guidance_type=args.guidance_type,
                guidance_scale=args.guidance_scale,
            )

            self._args = args
            self._model = model
            self._pipe = pipe
            self._device = device

    def unload(self) -> dict:
        with self._lock:
            self._pipe = None
            self._model = None
            self._extra_style_refs = None
            self._cached_feats = None
            gc.collect()
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
        return self.get_status()

    def synthesize_pil_96(
        self,
        char: str,
        style_pils_96: list[Image.Image],
        num_inference_steps: int = 20,
        guidance_scale: float = 7.5,
        seed: int = 42,
    ) -> Image.Image:
        """Run FontDiffuser DPM-Solver++ sampling for one character and return 96x96 RGB PIL image."""
        if not style_pils_96:
            raise ValueError("至少需要 1 个风格参考字形")

        self.ensure_loaded()
        import torch
        import torchvision.transforms as transforms

        tf = transforms.Compose(
            [
                transforms.Resize((96, 96), interpolation=transforms.InterpolationMode.BILINEAR),
                transforms.ToTensor(),
                transforms.Normalize([0.5], [0.5]),
            ]
        )

        content_pil = render_content_image(char, size=96)
        content_tensor = tf(content_pil)[None, :].to(device=self._device, dtype=torch.float32)

        style_tensors = torch.stack([tf(p) for p in style_pils_96], dim=0).to(
            device=self._device, dtype=torch.float32
        )
        primary_style_tensor = style_tensors[0:1]

        with self._lock:
            self._pipe.guidance_scale = float(guidance_scale)
            self._extra_style_refs = style_tensors if len(style_pils_96) > 1 else None
            self._cached_feats = None
            generator = torch.Generator(device="cpu").manual_seed(int(seed) & 0xFFFFFFFF)
            try:
                with torch.no_grad():
                    images = self._pipe.generate(
                        content_images=content_tensor,
                        style_images=primary_style_tensor,
                        batch_size=1,
                        order=2,
                        num_inference_step=int(num_inference_steps),
                        content_encoder_downsample_size=3,
                        dm_size=(96, 96),
                        algorithm_type="dpmsolver++",
                        skip_type="time_uniform",
                        method="multistep",
                        correcting_x0_fn=None,
                        generator=generator,
                    )
            finally:
                self._extra_style_refs = None
                self._cached_feats = None
        return images[0]

    def synthesize(self, char: str, style_ref_paths: list[Path], seed: int = 0) -> Optional[bytes]:
        if not self.is_available() or not style_ref_paths:
            return None
        import io

        style_pils = [glyph_png_to_style_96(p, size=96) for p in style_ref_paths[:4]]
        out_96 = self.synthesize_pil_96(char, style_pils, seed=seed)
        res = postprocess_generated_glyph(out_96, target_height_ratio=0.62)
        buf = io.BytesIO()
        res["rgba_image"].save(buf, format="PNG")
        return buf.getvalue()


_SYNTHESIZER = FontDiffuserSynthesizer()


def get_synthesizer() -> FontDiffuserSynthesizer:
    return _SYNTHESIZER


# Background batch job manager (serialized on single GPU worker lock)
_JOBS_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}


def start_synthesis_job(
    profile_id: str,
    chars: str,
    variants_per_char: int = 1,
    num_inference_steps: int = 20,
    guidance_scale: float = 7.5,
    style_glyph_ids: Optional[list[str]] = None,
    seed: int = 42,
    replace_existing_ai: bool = False,
) -> dict[str, Any]:
    """Validate references, enqueue background synthesis job, and return initial job status."""
    unique_chars = _dedup_chars(chars)
    if not unique_chars:
        raise ValueError("待推理字符不能为空")

    synth = get_synthesizer()
    status = synth.get_status()
    if not status["available"]:
        raise RuntimeError(status["error"] or "本地 AI 推理环境尚未就绪")

    refs = select_style_references(profile_id, style_glyph_ids=style_glyph_ids, max_refs=4)
    if not refs:
        raise ValueError("当前笔迹档案暂无平板真迹样本，请先通过采集表录入至少 1 个汉字作为风格参考")

    style_pils = [glyph_png_to_style_96(Path(r["image_path"]), size=96) for r in refs]
    target_h_ratio = get_target_height_ratio(profile_id)

    num_variants = max(1, min(3, variants_per_char))
    total_tasks = len(unique_chars) * num_variants

    job_id = uuid.uuid4().hex[:12]
    job_state: dict[str, Any] = {
        "job_id": job_id,
        "status": "running",
        "profile_id": profile_id,
        "total": total_tasks,
        "completed": 0,
        "current_char": unique_chars[0],
        "generated_glyphs": [],
        "replaced_count": 0,
        "errors": [],
        "elapsed_sec": 0.0,
    }
    with _JOBS_LOCK:
        _JOBS[job_id] = job_state

    def _worker() -> None:
        t0 = time.monotonic()
        ensure_data_dirs()
        out_dir = get_glyphs_dir() / profile_id
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            idx = 0
            for ch in unique_chars:
                old_ai_rows: list[tuple[str, str]] = []
                if replace_existing_ai:
                    with get_conn() as conn:
                        rows = conn.execute(
                            """
                            SELECT id, image_path FROM glyphs
                            WHERE profile_id = ? AND char = ? AND source = 'ai_generated'
                            """,
                            (profile_id, ch),
                        ).fetchall()
                        old_ai_rows = [(r["id"], r["image_path"]) for r in rows]

                char_success_count = 0
                for var_idx in range(1, num_variants + 1):
                    with _JOBS_LOCK:
                        job_state["current_char"] = ch

                    try:
                        # Rotate primary style ref slightly across variants for natural diversity
                        rotated_pils = (
                            style_pils[idx % len(style_pils) :] + style_pils[: idx % len(style_pils)]
                        )
                        pil_96 = synth.synthesize_pil_96(
                            char=ch,
                            style_pils_96=rotated_pils,
                            num_inference_steps=num_inference_steps,
                            guidance_scale=guidance_scale,
                            seed=seed + idx * 131,
                        )
                        metrics = postprocess_generated_glyph(pil_96, target_height_ratio=target_h_ratio)

                        glyph_id = uuid.uuid4().hex[:16]
                        out_path = out_dir / f"{glyph_id}.png"
                        metrics["rgba_image"].save(str(out_path), format="PNG")
                        created_at = now_iso()

                        with get_conn() as conn:
                            conn.execute(
                                """
                                INSERT INTO glyphs (
                                    id, profile_id, char, source, image_path,
                                    bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                                    visual_width_ratio, visual_height_ratio, ink_center_y,
                                    sheet_id, created_at
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                                """,
                                (
                                    glyph_id,
                                    profile_id,
                                    ch,
                                    "ai_generated",
                                    str(out_path),
                                    metrics["bbox_x0"],
                                    metrics["bbox_y0"],
                                    metrics["bbox_x1"],
                                    metrics["bbox_y1"],
                                    metrics["visual_width_ratio"],
                                    metrics["visual_height_ratio"],
                                    metrics["ink_center_y"],
                                    created_at,
                                ),
                            )

                        char_success_count += 1
                        with _JOBS_LOCK:
                            job_state["generated_glyphs"].append(
                                {
                                    "id": glyph_id,
                                    "char": ch,
                                    "variant": var_idx,
                                    "image_url": f"/api/glyphs/{glyph_id}/image",
                                }
                            )
                    except Exception as exc:
                        with _JOBS_LOCK:
                            job_state["errors"].append(f"{ch}: {exc}")
                    finally:
                        idx += 1
                        with _JOBS_LOCK:
                            job_state["completed"] = idx
                            job_state["elapsed_sec"] = round(time.monotonic() - t0, 2)

                if replace_existing_ai and char_success_count > 0 and old_ai_rows:
                    old_ids = [row_id for row_id, _ in old_ai_rows]
                    with get_conn() as conn:
                        placeholders = ",".join("?" for _ in old_ids)
                        conn.execute(
                            f"DELETE FROM glyphs WHERE profile_id = ? AND id IN ({placeholders})",
                            (profile_id, *old_ids),
                        )
                    for _, old_path in old_ai_rows:
                        p = Path(old_path)
                        if p.exists():
                            p.unlink(missing_ok=True)
                    with _JOBS_LOCK:
                        job_state["replaced_count"] += len(old_ai_rows)

            with _JOBS_LOCK:
                job_state["status"] = "done"
                job_state["elapsed_sec"] = round(time.monotonic() - t0, 2)
        except Exception as exc:
            with _JOBS_LOCK:
                job_state["status"] = "error"
                job_state["errors"].append(str(exc))
                job_state["elapsed_sec"] = round(time.monotonic() - t0, 2)

    thread = threading.Thread(target=_worker, daemon=True, name=f"ai-synth-{job_id}")
    thread.start()

    with _JOBS_LOCK:
        return dict(job_state)


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    with _JOBS_LOCK:
        st = _JOBS.get(job_id)
        if st is None:
            return None
        return {
            **st,
            "generated_glyphs": list(st["generated_glyphs"]),
            "errors": list(st["errors"]),
        }
