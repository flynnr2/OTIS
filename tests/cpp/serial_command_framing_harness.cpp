#include <iostream>

#include "otis_serial_command.h"

namespace {

void process_complete_frame(OtisSerialFrameCollector *collector) {
  if (otis_serial_frame_validate(collector) !=
      OtisSerialFrameValidation::Valid) {
    std::cout << "DIAG_REJECTED_INVALID_CHARACTER\n";
    otis_serial_frame_collector_init(collector);
    return;
  }

  OtisParsedSerialCommand command =
      otis_serial_command_parse(collector->line);
  switch (command.kind) {
    case OtisSerialCommandKind::Help:
      std::cout << "EXEC_HELP\n";
      break;
    case OtisSerialCommandKind::DacSet:
      std::cout << (command.arguments_valid ? "EXEC_DAC_SET"
                                            : "DIAG_REJECTED_DAC_ARGUMENT")
                << '\n';
      break;
    case OtisSerialCommandKind::SweepStart:
      std::cout << "EXEC_SWEEP_START\n";
      break;
    case OtisSerialCommandKind::Unknown:
    case OtisSerialCommandKind::SweepOther:
      std::cout << "DIAG_REJECTED_UNKNOWN\n";
      break;
    case OtisSerialCommandKind::Empty:
      break;
    default:
      std::cout << "EXEC_OTHER\n";
      break;
  }
  otis_serial_frame_collector_init(collector);
}

}  // namespace

int main() {
  OtisSerialFrameCollector collector;
  otis_serial_frame_collector_init(&collector);

  char byte = '\0';
  while (std::cin.get(byte)) {
    OtisSerialFrameEvent event =
        otis_serial_frame_collect(&collector, byte);
    if (event == OtisSerialFrameEvent::RejectedTooLong) {
      std::cout << "DIAG_REJECTED_TOO_LONG\n";
    } else if (event == OtisSerialFrameEvent::Complete) {
      process_complete_frame(&collector);
    }
  }
  return 0;
}
