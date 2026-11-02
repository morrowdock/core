@_exported import MorrowdockCore
#if canImport(MorrowdockPrivate)
import MorrowdockPrivate
#endif
public enum PrivateExtension {
 public static var isAvailable: Bool {
  #if canImport(MorrowdockPrivate)
  return true
  #else
  return false
  #endif
 }
}
