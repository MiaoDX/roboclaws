#!/usr/bin/env bash

# Source before starting Vulkan or Isaac in a container with the pinned driver overlay.

_roboclaws_overlay_version=580.105.08
_roboclaws_overlay_root=${ROBOCLAWS_NVIDIA_OVERLAY_ROOT:-/opt/nvidia-driver-${_roboclaws_overlay_version}}
_roboclaws_clean_ld_library_path=

IFS=: read -r -a _roboclaws_ld_parts <<< "${LD_LIBRARY_PATH:-}"
for _roboclaws_ld_part in "${_roboclaws_ld_parts[@]}"; do
  if [[ -z "$_roboclaws_ld_part" || "$_roboclaws_ld_part" == "$_roboclaws_overlay_root" ]]; then
    continue
  fi
  if [[ -z "$_roboclaws_clean_ld_library_path" ]]; then
    _roboclaws_clean_ld_library_path=$_roboclaws_ld_part
  else
    _roboclaws_clean_ld_library_path+=:$_roboclaws_ld_part
  fi
done

mapfile -t _roboclaws_driver_versions < <(
  nvidia-smi --query-gpu=driver_version --format=csv,noheader \
    | sed '/^[[:space:]]*$/d' \
    | sort -u
)
if [[ ${#_roboclaws_driver_versions[@]} -ne 1 ]]; then
  echo "ROBOCLAWS_NVIDIA_VULKAN_RUNTIME unsupported_driver_set=${_roboclaws_driver_versions[*]:-missing}" >&2
  return 78
fi

export ROBOCLAWS_NVIDIA_DRIVER_VERSION=${_roboclaws_driver_versions[0]}
case "$ROBOCLAWS_NVIDIA_DRIVER_VERSION" in
  570.124.06)
    export LD_LIBRARY_PATH=$_roboclaws_clean_ld_library_path
    export ROBOCLAWS_NVIDIA_VULKAN_RUNTIME_MODE=native
    ;;
  580.105.08)
    if [[ ! -r "$_roboclaws_overlay_root/libGLX_nvidia.so.0" || \
          ! -r "$_roboclaws_overlay_root/libnvidia-glvkspirv.so.580.105.08" || \
          ! -r "$_roboclaws_overlay_root/libnvidia-gpucomp.so.580.105.08" ]]; then
      echo "ROBOCLAWS_NVIDIA_VULKAN_RUNTIME missing_overlay=$_roboclaws_overlay_root" >&2
      return 78
    fi
    export LD_LIBRARY_PATH=$_roboclaws_overlay_root${_roboclaws_clean_ld_library_path:+:$_roboclaws_clean_ld_library_path}
    export ROBOCLAWS_NVIDIA_VULKAN_RUNTIME_MODE=overlay
    ;;
  *)
    echo "ROBOCLAWS_NVIDIA_VULKAN_RUNTIME unsupported_driver=$ROBOCLAWS_NVIDIA_DRIVER_VERSION" >&2
    return 78
    ;;
esac

export VK_DRIVER_FILES=/etc/vulkan/icd.d/nvidia_icd.json
export VK_ICD_FILENAMES=/etc/vulkan/icd.d/nvidia_icd.json
echo "ROBOCLAWS_NVIDIA_VULKAN_RUNTIME driver=$ROBOCLAWS_NVIDIA_DRIVER_VERSION mode=$ROBOCLAWS_NVIDIA_VULKAN_RUNTIME_MODE"

unset _roboclaws_overlay_version _roboclaws_overlay_root
unset _roboclaws_clean_ld_library_path _roboclaws_ld_parts _roboclaws_ld_part
unset _roboclaws_driver_versions
