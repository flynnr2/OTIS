#include <iostream>
#include <string>
#include <vector>

#include "otis_serial_command.h"
#include "otis_setup_authority.h"

namespace {

bool arguments_accept(const OtisParsedSerialCommand &command) {
  if (!command.arguments_valid) return false;
  uint32_t values[3] = {};
  switch (command.kind) {
    case OtisSerialCommandKind::ActiveSnapshot:
    case OtisSerialCommandKind::ActiveLease:
      return otis_serial_command_parse_nonzero_decimal_u32_fields(
          command.text_argument, values, 1u);
    case OtisSerialCommandKind::ActiveArm:
      return otis_serial_command_parse_nonzero_decimal_u32_fields(
          command.text_argument, values, 3u);
    case OtisSerialCommandKind::ActiveEvidence:
      return otis_serial_command_parse_active_evidence(
          command.text_argument, &values[0], &values[1]);
    case OtisSerialCommandKind::ActiveSetup: {
      OtisSetupAuthorityRequest request = {};
      return otis_setup_authority_parse_request(command.text_argument, &request);
    }
    case OtisSerialCommandKind::Empty:
    case OtisSerialCommandKind::Unknown:
      return false;
    default:
      return true;
  }
}

}  // namespace

int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    std::vector<char> mutable_line(line.begin(), line.end());
    mutable_line.push_back('\0');
    const OtisParsedSerialCommand parsed =
        otis_serial_command_parse(mutable_line.data());
    std::cout << (arguments_accept(parsed) ? "ACCEPT" : "REJECT") << '\n';
  }
  return 0;
}
