{
  description = "dystemctl - systemd emulation for Darwin";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    flake-parts.url = "github:hercules-ci/flake-parts";

    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    git-hooks-nix = {
      url = "github:cachix/git-hooks.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs = {
        pyproject-nix.follows = "pyproject-nix";
        uv2nix.follows = "uv2nix";
        nixpkgs.follows = "nixpkgs";
      };
    };
  };

  outputs =
    inputs@{
      self,
      nixpkgs,
      flake-parts,
      treefmt-nix,
      git-hooks-nix,
      uv2nix,
      pyproject-nix,
      pyproject-build-systems,
      ...
    }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = [
        "aarch64-darwin"
        "x86_64-darwin"
      ];

      imports = [
        treefmt-nix.flakeModule
        git-hooks-nix.flakeModule
      ];

      perSystem =
        {
          config,
          self',
          inputs',
          pkgs,
          system,
          ...
        }:
        let
          workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };

          overlay = workspace.mkPyprojectOverlay {
            sourcePreference = "wheel";
          };

          python = pkgs.python313;

          pythonSet = (pkgs.callPackage pyproject-nix.build.packages { inherit python; }).overrideScope (
            nixpkgs.lib.composeManyExtensions [
              pyproject-build-systems.overlays.default
              overlay
            ]
          );

          venv = pythonSet.mkVirtualEnv "dystemctl-env" workspace.deps.default;
        in
        {
          treefmt = {
            projectRootFile = "flake.nix";

            programs = {
              nixfmt.enable = true;
              ruff-check.enable = true;
              ruff-format.enable = true;
            };

            settings = {
              global.excludes = [
                ".venv/*"
                ".git/*"
                "*.lock"
              ];

              formatter = {
                ruff-check.priority = 1;
                ruff-format.priority = 2;
              };
            };
          };

          pre-commit = {
            check.enable = true;

            settings = {
              hooks = {
                treefmt = {
                  enable = true;
                  package = config.treefmt.build.wrapper;
                };

                commitizen = {
                  enable = true;
                  stages = [ "commit-msg" ];
                };

                ruff.enable = true;
                ruff-format.enable = true;
              };
            };
          };

          packages = {
            default = venv;
            dystemctl = pythonSet.dystemctl;

            changelog = pkgs.runCommand "changelog" { } ''
              cd ${self}
              ${pkgs.git-cliff}/bin/git-cliff --config ${./cliff.toml} > $out
            '';
          };

          apps = {
            default = {
              type = "app";
              program = "${venv}/bin/dystemctl";
            };

            systemctl = {
              type = "app";
              program = "${venv}/bin/systemctl";
            };

            journalctl = {
              type = "app";
              program = "${venv}/bin/journalctl";
            };
          };

          devShells.default = pkgs.mkShell {
            packages = [
              venv
              pkgs.uv
              pkgs.git-cliff
              pkgs.commitizen
            ];

            shellHook = ''
              unset PYTHONPATH
              export UV_NO_SYNC=1
              ${config.pre-commit.installationScript}
            '';
          };
        };

      flake = {
        overlays.default = final: prev: {
          dystemctl = self.packages.${prev.system}.default;
        };
      };
    };
}
