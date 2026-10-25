// Host-only ABI probe for the pinned Android 16 APEX manifest schema.
#include <fstream>
#include <iostream>
#include <string>

#include "apex_manifest.pb.h"

int main(int argc, char** argv) {
    if (argc != 2) {
        std::cerr << "usage: apex_manifest_probe <apex_manifest.pb>\n";
        return 2;
    }
    std::ifstream input(argv[1], std::ios::binary);
    apex::proto::ApexManifest metadata;
    if (!input || !metadata.ParseFromIstream(&input) || metadata.name().empty()) {
        std::cerr << "invalid APEX manifest\n";
        return 1;
    }
    std::cout << "name=" << metadata.name() << " version=" << metadata.version()
              << " requires=" << metadata.requirenativelibs_size() << '\n';
    return 0;
}
