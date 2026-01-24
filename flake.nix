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

    files = {
      url = "github:mightyiam/files";
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
      files,
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
        files.flakeModules.default
      ];

      perSystem =
        {
          config,
          self',
          inputs',
          pkgs,
          system,
          lib,
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

          # YAML format helper
          yaml = pkgs.formats.yaml { };

          # Renovate configuration
          renovateConfig = {
            "$schema" = "https://docs.renovatebot.com/renovate-schema.json";
            extends = [
              "config:recommended"
              ":semanticCommits"
              ":automergeMinor"
              ":automergeDigest"
              "group:allNonMajor"
            ];
            labels = [ "dependencies" ];
            schedule = [ "before 6am on monday" ];
            timezone = "America/Los_Angeles";
            packageRules = [
              {
                description = "Python dependencies";
                matchManagers = [
                  "pip_requirements"
                  "pep621"
                ];
                groupName = "python dependencies";
              }
              {
                description = "GitHub Actions";
                matchManagers = [ "github-actions" ];
                groupName = "github actions";
                automerge = true;
              }
              {
                description = "Nix flake inputs";
                matchManagers = [ "nix" ];
                groupName = "nix flake inputs";
              }
              {
                description = "Homebrew formula resources";
                matchFileNames = [ "Formula/*.rb" ];
                enabled = false;
              }
              {
                description = "Auto-merge patch updates";
                matchUpdateTypes = [ "patch" ];
                automerge = true;
              }
              {
                description = "Auto-merge dev dependencies";
                matchDepTypes = [
                  "devDependencies"
                  "dev"
                ];
                automerge = true;
              }
            ];
            nix.enabled = true;
            lockFileMaintenance = {
              enabled = true;
              schedule = [ "before 6am on the first day of the month" ];
            };
          };

          # Build workflow
          buildWorkflow = {
            name = "Build";
            on = {
              push = {
                branches = [ "main" ];
                tags = [ "v*" ];
              };
              pull_request.branches = [ "main" ];
              workflow_dispatch = { };
            };
            jobs = {
              test = {
                runs-on = "macos-latest";
                strategy.matrix.python-version = [
                  "3.12"
                  "3.13"
                ];
                steps = [
                  { uses = "actions/checkout@v6"; }
                  {
                    name = "Install uv";
                    uses = "astral-sh/setup-uv@v7";
                    "with".version = "latest";
                  }
                  {
                    name = "Set up Python \${{ matrix.python-version }}";
                    run = "uv python install \${{ matrix.python-version }}";
                  }
                  {
                    name = "Install dependencies";
                    run = "uv sync --dev";
                  }
                  {
                    name = "Run tests";
                    run = "uv run pytest tests/ --cov=dystemctl --cov-report=xml";
                  }
                  {
                    name = "Upload coverage";
                    uses = "codecov/codecov-action@v5";
                    "if" = "matrix.python-version == '3.13'";
                    "with" = {
                      files = "coverage.xml";
                      fail_ci_if_error = false;
                    };
                  }
                ];
              };

              build = {
                runs-on = "macos-latest";
                needs = [ "test" ];
                steps = [
                  { uses = "actions/checkout@v6"; }
                  {
                    name = "Install uv";
                    uses = "astral-sh/setup-uv@v7";
                    "with".version = "latest";
                  }
                  {
                    name = "Set up Python";
                    run = "uv python install 3.13";
                  }
                  {
                    name = "Build package";
                    run = "uv build";
                  }
                  {
                    name = "Upload dist";
                    uses = "actions/upload-artifact@v6";
                    "with" = {
                      name = "dist";
                      path = "dist/*";
                    };
                  }
                ];
              };

              publish = {
                runs-on = "macos-latest";
                needs = [ "build" ];
                "if" = "startsWith(github.ref, 'refs/tags/v')";
                permissions.id-token = "write";
                steps = [
                  {
                    name = "Download dist";
                    uses = "actions/download-artifact@v7";
                    "with".name = "dist";
                  }
                  {
                    name = "Publish to PyPI";
                    uses = "pypa/gh-action-pypi-publish@release/v1";
                    "with".skip-existing = true;
                  }
                ];
              };

              release = {
                runs-on = "macos-latest";
                needs = [ "build" ];
                "if" = "startsWith(github.ref, 'refs/tags/v')";
                permissions.contents = "write";
                steps = [
                  { uses = "actions/checkout@v6"; }
                  {
                    name = "Download dist";
                    uses = "actions/download-artifact@v7";
                    "with".name = "dist";
                  }
                  {
                    name = "Create GitHub Release";
                    uses = "softprops/action-gh-release@v2";
                    "with" = {
                      files = "dist/*";
                      generate_release_notes = true;
                    };
                  }
                ];
              };
            };
          };

          # Nix workflow
          nixWorkflow = {
            name = "Nix";
            on = {
              push.branches = [ "main" ];
              pull_request.branches = [ "main" ];
              workflow_dispatch = { };
            };
            jobs.build = {
              runs-on = "macos-latest";
              steps = [
                { uses = "actions/checkout@v6"; }
                {
                  name = "Install Nix";
                  uses = "DeterminateSystems/nix-installer-action@main";
                }
                {
                  name = "Setup Nix cache";
                  uses = "DeterminateSystems/magic-nix-cache-action@main";
                }
                {
                  name = "Check flake";
                  run = "nix flake check";
                }
                {
                  name = "Build package";
                  run = "nix build";
                }
                {
                  name = "Test systemctl --help";
                  run = "nix run .#systemctl -- --help";
                }
                {
                  name = "Test journalctl --help";
                  run = "nix run .#journalctl -- --help";
                }
              ];
            };
          };

          # Homebrew workflow
          homebrewWorkflow = {
            name = "Homebrew";
            on = {
              push.branches = [ "main" ];
              pull_request.branches = [ "main" ];
              workflow_dispatch = { };
            };
            jobs.build = {
              runs-on = "macos-latest";
              steps = [
                { uses = "actions/checkout@v6"; }
                {
                  name = "Set up Homebrew";
                  uses = "Homebrew/actions/setup-homebrew@master";
                }
                {
                  name = "Tap local formula";
                  run = "brew tap-new --no-git local/dystemctl && cp Formula/dystemctl.rb $(brew --repository local/dystemctl)/Formula/";
                }
                {
                  name = "Install from source";
                  run = "brew install --build-from-source --verbose local/dystemctl/dystemctl";
                }
                {
                  name = "Test systemctl";
                  run = "brew test local/dystemctl/dystemctl";
                }
                {
                  name = "Test commands";
                  run = ''
                    systemctl --help
                    journalctl --help
                    systemctl status | head -20
                  '';
                }
              ];
            };
          };
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

                write-files = {
                  enable = true;
                  name = "write-files";
                  description = "Regenerate files from Nix definitions";
                  entry = "${config.files.writer.drv}/bin/write-files";
                  files = "\\.nix$";
                  pass_filenames = false;
                };
              };
            };
          };

          # Generated files
          files.files = [
            {
              path_ = ".github/renovate.json";
              drv = pkgs.writeText "renovate.json" (builtins.toJSON renovateConfig);
            }
            {
              path_ = ".github/workflows/build.yml";
              drv = yaml.generate "build.yml" buildWorkflow;
            }
            {
              path_ = ".github/workflows/nix.yml";
              drv = yaml.generate "nix.yml" nixWorkflow;
            }
            {
              path_ = ".github/workflows/homebrew.yml";
              drv = yaml.generate "homebrew.yml" homebrewWorkflow;
            }
          ];

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
              config.files.writer.drv
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
