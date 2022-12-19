import torch
from PIL import Image
import torchvision.transforms as T
from tqdm.auto import tqdm
from models.stable_diffusion.cache_objects import (
    cache_obj,
    schedulers,
)
from models.stable_diffusion.stable_args import args
from models.stable_diffusion.utils import generate_initial_latents
from random import randint
import numpy as np
import time


def set_ui_params(prompt, negative_prompt, steps, guidance_scale, seed):
    args.prompts = [prompt]
    args.negative_prompts = [negative_prompt]
    args.steps = steps
    args.guidance_scale = guidance_scale
    args.seed = seed


def stable_diff_inf(
    prompt: str,
    negative_prompt: str,
    steps: int,
    guidance_scale: float,
    seed: int,
    scheduler_key: str,
):

    # Handle out of range seeds.
    uint32_info = np.iinfo(np.uint32)
    uint32_min, uint32_max = uint32_info.min, uint32_info.max
    if seed < uint32_min or seed >= uint32_max:
        seed = randint(uint32_min, uint32_max)

    guidance_scale = torch.tensor(guidance_scale).to(torch.float32)
    set_ui_params(prompt, negative_prompt, steps, guidance_scale, seed)
    dtype = torch.float32 if args.precision == "fp32" else torch.half

    # get model height and width.
    height = 512
    width = 512
    if args.version == "v2.1":
        height = 768
        width = 768

    if not cache_obj["init"]["seed"] == args.seed:
        latents = generate_initial_latents(height, width)
        cache_obj["init"] = {
            "seed": args.seed,
            "latents": latents,
        }
    else:
        latents = cache_obj["init"]["latents"]

    # Initialize vae and unet models.
    vae, unet, clip, tokenizer = (
        cache_obj["vae"],
        cache_obj["unet"],
        cache_obj["clip"],
        cache_obj["tokenizer"],
    )
    scheduler = schedulers[scheduler_key]
    cpu_scheduling = not scheduler_key.startswith("Shark")

    start = time.time()
    text_input = tokenizer(
        args.prompts,
        padding="max_length",
        max_length=args.max_length,
        truncation=True,
        return_tensors="pt",
    )
    max_length = text_input.input_ids.shape[-1]
    uncond_input = tokenizer(
        args.negative_prompts,
        padding="max_length",
        max_length=max_length,
        truncation=True,
        return_tensors="pt",
    )
    text_input = torch.cat([uncond_input.input_ids, text_input.input_ids])

    clip_inf_start = time.time()
    text_embeddings = clip.forward((text_input,))
    clip_inf_end = time.time()
    text_embeddings = torch.from_numpy(text_embeddings).to(dtype)
    text_embeddings_numpy = text_embeddings.detach().numpy()

    scheduler.set_timesteps(args.steps)
    scheduler.is_scale_input_called = True

    latents = latents * scheduler.init_noise_sigma

    avg_ms = 0
    for i, t in tqdm(enumerate(scheduler.timesteps)):

        step_start = time.time()
        timestep = torch.tensor([t]).to(dtype).detach().numpy()
        latent_model_input = scheduler.scale_model_input(latents, t)
        if cpu_scheduling:
            latent_model_input = latent_model_input.detach().numpy()

        noise_pred = unet.forward(
            (
                latent_model_input,
                timestep,
                text_embeddings_numpy,
                args.guidance_scale,
            ),
            send_to_host=False,
        )

        if cpu_scheduling:
            noise_pred = torch.from_numpy(noise_pred.to_host())
            latents = scheduler.step(noise_pred, t, latents).prev_sample
        else:
            latents = scheduler.step(noise_pred, t, latents)
        step_time = time.time() - step_start
        avg_ms += step_time
        step_ms = int((step_time) * 1000)
        if not args.hide_steps:
            print(f" \nIteration = {i}, Time = {step_ms}ms")

    # scale and decode the image latents with vae
    latents_numpy = latents
    if cpu_scheduling:
        latents_numpy = latents.detach().numpy()
    vae_start = time.time()
    images = vae.forward((latents_numpy,))
    vae_end = time.time()
    end_time = time.time()

    avg_ms = 1000 * avg_ms / args.steps
    clip_inf_time = (clip_inf_end - clip_inf_start) * 1000
    vae_inf_time = (vae_end - vae_start) * 1000
    total_time = end_time - start
    print(f"\nAverage step time: {avg_ms}ms/it")
    print(f"Clip Inference time (ms) = {clip_inf_time:.3f}")
    print(f"VAE Inference time (ms): {vae_inf_time:.3f}")
    print(f"\nTotal image generation time: {total_time}sec")

    # generate outputs to web.
    transform = T.ToPILImage()
    pil_images = [
        transform(image) for image in torch.from_numpy(images).to(torch.uint8)
    ]

    text_output = f"prompt={args.prompts}"
    text_output += f"\nnegative prompt={args.negative_prompts}"
    text_output += f"\nsteps={args.steps}, guidance_scale={args.guidance_scale}, scheduler={scheduler_key}, seed={args.seed}, size={height}x{width}, version={args.version}"
    text_output += f"\nAverage step time: {avg_ms:.2f}ms/it"
    text_output += f"\nTotal image generation time: {total_time:.2f}sec"

    return pil_images[0], text_output
