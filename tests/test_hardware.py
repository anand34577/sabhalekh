from sabhalekh.hardware import HardwareInfo, HardwareManager, is_oom_error, select_profile_name


def manager(**kw) -> HardwareManager:
    return HardwareManager(prober=lambda: HardwareInfo(cpu_cores=6, cpu_threads=12, ram_mb=16000,
                                                       ram_available_mb=8000, free_disk_mb=100000, **kw))


def test_rtx_high_vram_uses_fp16_batched():
    p = manager(cuda_available=True, gpu_name="NVIDIA GeForce RTX 4060", vram_mb=8188,
                compute_capability="8.9").profile()
    assert (p.name, p.device, p.compute_type, p.batch_size) == ("gpu_high", "cuda", "float16", 8)
    assert p.badge(manager(gpu_name="NVIDIA GeForce RTX 4060").info) == "GPU Mode: RTX 4060"


def test_gtx_1650_4gb_is_low_vram_int8():
    hm = manager(cuda_available=True, gpu_name="NVIDIA GeForce GTX 1650", vram_mb=4096, compute_capability="7.5")
    p = hm.profile()
    assert (p.name, p.compute_type, p.free_between_stages) == ("gpu_low", "int8_float16", True)
    assert hm.status()["badge"] == "GPU Mode: GTX 1650"


def test_gtx_16xx_with_6gb_avoids_slow_fp16():
    p = manager(cuda_available=True, gpu_name="NVIDIA GeForce GTX 1660 Ti", vram_mb=6144,
                compute_capability="7.5").profile()
    assert p.name == "gpu_high" and p.compute_type == "int8_float16"


def test_no_gpu_uses_cpu_with_physical_cores():
    p = manager().profile()
    assert (p.name, p.device, p.compute_type, p.threads) == ("cpu", "cpu", "int8", 6)
    assert p.badge({}) == "CPU Mode (6 threads)"


def test_gpu_found_but_cuda_broken_falls_back_to_cpu():
    hm = manager(cuda_available=False, gpu_name="NVIDIA GeForce GTX 1650", vram_mb=4096,
                 cuda_error="cublas64_12.dll not found")
    assert hm.profile().name == "cpu"


def test_override_respected_only_when_possible():
    assert select_profile_name({"cuda_available": True, "vram_mb": 4096}, "cpu_fast") == "cpu_fast"
    assert select_profile_name({"cuda_available": False}, "gpu_high") == "cpu"
    assert select_profile_name({"cuda_available": True, "vram_mb": 4096}, "gpu_high") == "gpu_high"


def test_oom_downgrade_chain():
    hm = manager(cuda_available=True, gpu_name="RTX 3060", vram_mb=12288, compute_capability="8.6")
    chain, p = [], hm.profile()
    while p:
        chain.append(p.name)
        p = hm.downgrade(p)
    assert chain == ["gpu_high", "gpu_low", "cpu", "cpu_fast"]
    cpu_only = manager()
    assert cpu_only.downgrade(cpu_only.profile()).name == "cpu_fast"


def test_oom_detection():
    assert is_oom_error(RuntimeError("CUDA failed with error out of memory"))
    assert is_oom_error(RuntimeError("CUBLAS_STATUS_ALLOC_FAILED"))
    assert not is_oom_error(ValueError("bad input"))


GTX_VK = {"name": "Vulkan1", "description": "NVIDIA GeForce GTX 1650", "kind": "vulkan", "type": "gpu",
          "device_id": "0000:01:00.0", "memory_mb": 4149, "memory_free_mb": 3500}
RADEON_VK = {"name": "Vulkan0", "description": "AMD Radeon(TM) Graphics", "kind": "vulkan", "type": "igpu",
             "device_id": None, "memory_mb": 12207, "memory_free_mb": 11000}


def test_gtx_1650_with_igpu_runs_nemotron_on_the_discrete_gpu():
    hm = manager(cuda_available=True, gpu_name="NVIDIA GeForce GTX 1650", vram_mb=4096, compute_capability="7.5",
                 accel_devices=[RADEON_VK, GTX_VK])
    p = hm.profile()
    assert (p.name, p.accel, p.device) == ("gpu_low", "gpu", "cuda")
    chain = []
    while p:
        chain.append((p.name, p.accel))
        p = hm.downgrade(p)
    assert chain == [("gpu_low", "gpu"), ("igpu", "igpu"), ("cpu", "cpu"), ("cpu_fast", "cpu")]
    assert hm.profile("igpu").badge(hm.info) == "iGPU Mode: AMD Radeon Graphics"


def test_vulkan_gpu_without_cuda_still_uses_the_gpu_for_nemotron():
    hm = manager(cuda_available=False, gpu_name="NVIDIA GeForce GTX 1650", cuda_error="cublas64_12.dll not found",
                 accel_devices=[GTX_VK])
    p = hm.profile()
    assert (p.name, p.accel, p.device) == ("gpu_low", "gpu", "cpu")  # Whisper would run on the CPU
    assert hm.status()["badge"] == "GPU Mode: GTX 1650"


def test_integrated_gpu_only_laptop_uses_igpu():
    hm = manager(accel_devices=[RADEON_VK])
    assert (hm.profile().name, hm.profile().accel) == ("igpu", "igpu")
    assert select_profile_name({"accel_devices": []}, "igpu") == "cpu"


def test_low_resources_warnings():
    from sabhalekh import hardware

    info = HardwareInfo(ram_mb=4096, ram_available_mb=1000, free_disk_mb=500)
    hm = HardwareManager(prober=lambda: info)
    assert hm.info["ram_mb"] == 4096
    real = hardware.probe()  # the real probe on this machine must not crash
    assert real.cpu_cores >= 1 and real.ram_mb > 0
