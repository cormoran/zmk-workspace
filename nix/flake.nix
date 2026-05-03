{
  description = "Zephyr (v4.1) flake for ZMK development";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    # Customize the version of Zephyr used by the flake here
    zephyr.url = "github:zmkfirmware/zephyr/v4.1.0+zmk-fixes";
    zephyr.flake = false;

    zephyr-nix.url = "github:nix-community/zephyr-nix";
    zephyr-nix.inputs.nixpkgs.follows = "nixpkgs";
    zephyr-nix.inputs.zephyr.follows = "zephyr";
  };

  outputs = { self, nixpkgs, zephyr-nix, ... }: let
    pkgs = nixpkgs.legacyPackages.x86_64-linux;
    zephyr = zephyr-nix.packages.x86_64-linux;
    pythonEnv = (zephyr.pythonEnv.override {
        extraPackages = ps: [
            # Use python version of protoc to avoid python path issue in protoc-generator
            ps.grpcio-tools
        ];
    });
  in {
    devShells.x86_64-linux.default = pkgs.mkShell {
        packages = [
            # SDK version compatibility: https://github.com/zephyrproject-rtos/sdk-ng/wiki/Zephyr-Version-Compatibility
            (zephyr.sdk-0_16.override {
                targets = [
                    "arm-zephyr-eabi"
                ];
            })
            pythonEnv
            # Use zephyr.hosttools-nix to use nixpkgs built tooling instead of official Zephyr binaries
            zephyr.hosttools-0_16
            pkgs.cmake
            pkgs.ninja
            pkgs.pre-commit
        ];
        env = {
            # system python is sometimes used due to incomplete nix env.
            # Setting PYTHONPATH to the nix env site-packages should make it work.
            PYTHONPATH = "${pythonEnv}/${pythonEnv.sitePackages}";
        };
        shellHook = ''
            source <(west completion bash)
        '';
    };
  };
  nixConfig = {
    bash-prompt-prefix = "(zmk-workspace) ";
  };
}
